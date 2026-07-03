"""Import a TV Time GDPR export zip: shows, episode history, movies, favorites.

The zip contains gdpr-data/*.csv. Relevant files:
  user_tv_show_data.csv        one row per show: name, TVDB id, favorite flag
  followed_tv_show.csv         active/archived flags per show
  user_show_special_status.csv 'for_later' watchlist entries
  tv_show_rate.csv             show ratings
  tracking-prod-records-v2.csv per-episode watch events (season/episode/date)
  tracking-prod-records.csv    movie follow/towatch/watch events

Shows are matched to TMDB via TVDB id (/find), movies via name+year search.
Runs in a background thread; progress is polled via GET /import/tvtime/status.
"""
import csv
import io
import threading
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import SessionLocal
from ..models import EpisodeWatch, MediaItem, MediaType, User, WatchStatus
from .tmdb import POSTER_BASE, _tmdb_get

router = APIRouter(prefix="/import", tags=["import"])

_progress: dict[int, dict] = {}


def _set(user_id: int, **kw):
    _progress.setdefault(user_id, {}).update(kw)


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    for entry in zf.namelist():
        if entry.endswith(name):
            with zf.open(entry) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace",
                                        newline="")
                return list(csv.DictReader(text))
    return []


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _find_tv_by_tvdb(tvdb_id: str) -> dict | None:
    try:
        data = _tmdb_get(f"/find/{tvdb_id}", {"external_source": "tvdb_id"})
        results = data.get("tv_results") or []
        return results[0] if results else None
    except Exception:
        return None


def _search_movie(name: str, year: str | None) -> dict | None:
    try:
        params = {"query": name, "include_adult": "false"}
        if year:
            params["primary_release_year"] = year
        data = _tmdb_get("/search/movie", params)
        results = data.get("results") or []
        if not results and year:  # retry without the year constraint
            data = _tmdb_get("/search/movie", {"query": name, "include_adult": "false"})
            results = data.get("results") or []
        return results[0] if results else None
    except Exception:
        return None


def _run_import(user_id: int, zip_bytes: bytes):
    db: Session = SessionLocal()
    summary = {"shows": 0, "episodes": 0, "movies": 0, "skipped": 0, "unmatched": []}
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

        show_rows = _read_csv(zf, "user_tv_show_data.csv")
        followed = {r["tv_show_id"]: r for r in _read_csv(zf, "followed_tv_show.csv")}
        for_later = {r["tv_show_id"] for r in _read_csv(zf, "user_show_special_status.csv")
                     if r.get("status") == "for_later"}
        rates = {r["tv_show_id"]: r for r in _read_csv(zf, "tv_show_rate.csv")}
        episode_events = _read_csv(zf, "tracking-prod-records-v2.csv")
        movie_events = _read_csv(zf, "tracking-prod-records.csv")

        existing_tmdb = {
            (i.media_type.value, i.tmdb_id)
            for i in db.query(MediaItem).filter(MediaItem.user_id == user_id)
            if i.tmdb_id
        }
        existing_titles = {
            (i.media_type.value, i.title.lower())
            for i in db.query(MediaItem).filter(MediaItem.user_id == user_id)
        }

        # ---------- shows ----------
        _set(user_id, stage="Matching shows", done=0, total=len(show_rows))
        items_by_tvdb: dict[str, MediaItem] = {}
        for n, row in enumerate(show_rows, 1):
            _set(user_id, done=n)
            tvdb_id = row.get("tv_show_id") or ""
            name = (row.get("tv_show_name") or "").strip()
            if not name:
                continue
            f = followed.get(tvdb_id, {})
            if tvdb_id in for_later:
                st = WatchStatus.want_to_watch
            elif f.get("archived") == "1":
                st = WatchStatus.dropped
            else:
                st = WatchStatus.watching

            found = _find_tv_by_tvdb(tvdb_id)
            tmdb_id = found["id"] if found else None
            final_title = (found["name"] if found else name).strip()
            # dedupe on BOTH the resolved tmdb id and the final canonical title —
            # different TVDB entries can resolve to the same TMDB show
            if (("tv_show", tmdb_id) in existing_tmdb and tmdb_id
                    or ("tv_show", final_title.lower()) in existing_titles):
                summary["skipped"] += 1
                continue
            if not found:
                summary["unmatched"].append(name)

            details = {}
            if tmdb_id:
                try:
                    raw = _tmdb_get(f"/tv/{tmdb_id}")
                    run_times = raw.get("episode_run_time") or []
                    details = {
                        "runtime_minutes": round(sum(run_times) / len(run_times))
                        if run_times else (raw.get("last_episode_to_air") or {}).get("runtime"),
                        "total_episodes": raw.get("number_of_episodes"),
                        "genres": ", ".join(g["name"] for g in raw.get("genres", []))[:300] or None,
                        "poster_url": f"{POSTER_BASE}{raw['poster_path']}"
                        if raw.get("poster_path") else None,
                    }
                except Exception:
                    details = {}

            rating = None
            rate_row = rates.get(tvdb_id)
            if rate_row and (rate_row.get("rating") or "").isdigit():
                raw_rating = int(rate_row["rating"])
                rating = min(10, raw_rating * 2 if raw_rating <= 5 else raw_rating)

            item = MediaItem(
                user_id=user_id,
                media_type=MediaType.tv_show,
                title=final_title,
                status=st,
                is_favorite=row.get("is_favorited") == "1",
                tmdb_id=tmdb_id,
                rating=rating,
                poster_url=details.get("poster_url"),
                runtime_minutes=details.get("runtime_minutes"),
                total_episodes=details.get("total_episodes"),
                genres=details.get("genres"),
                year=None,
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
            except IntegrityError:
                summary["skipped"] += 1
                continue
            items_by_tvdb[tvdb_id] = item
            existing_titles.add(("tv_show", final_title.lower()))
            if tmdb_id:
                existing_tmdb.add(("tv_show", tmdb_id))
            summary["shows"] += 1
            if n % 25 == 0:
                db.commit()
        db.commit()

        # ---------- per-episode history ----------
        _set(user_id, stage="Importing episode history",
             done=0, total=len(episode_events))
        seen: set[tuple] = set()
        for n, ev in enumerate(episode_events, 1):
            if n % 500 == 0:
                _set(user_id, done=n)
                db.commit()
            item = items_by_tvdb.get(ev.get("s_id") or "")
            s_no, ep_no = ev.get("s_no"), ev.get("ep_no")
            if not item or not s_no or not ep_no:
                continue
            try:
                season, episode = int(s_no), int(ep_no)
            except ValueError:
                continue
            key = (item.id, season, episode)
            if key in seen:
                continue
            seen.add(key)
            db.add(EpisodeWatch(
                media_item_id=item.id, season=season, episode=episode,
                watched_at=_parse_dt(ev.get("created_at")) or datetime.now(timezone.utc),
            ))
            summary["episodes"] += 1
        db.commit()

        # sync counters + auto-status per show
        for item in items_by_tvdb.values():
            watches = db.query(EpisodeWatch).filter(
                EpisodeWatch.media_item_id == item.id).all()
            if not watches:
                continue
            item.episodes_watched = len(watches)
            last = max(watches, key=lambda w: (w.season, w.episode))
            item.current_season, item.current_episode = last.season, last.episode
            if item.total_episodes and item.episodes_watched >= item.total_episodes:
                item.status = WatchStatus.completed
        db.commit()

        # ---------- movies ----------
        movies: dict[str, dict] = {}
        for ev in movie_events:
            name = (ev.get("movie_name") or "").strip()
            if not name:
                continue
            m = movies.setdefault(name, {"watched": False, "runtime": None,
                                         "year": None, "watched_at": None})
            if ev.get("type") in ("watch", "rewatch"):
                m["watched"] = True
                m["watched_at"] = m["watched_at"] or _parse_dt(ev.get("created_at"))
            runtime = ev.get("runtime")
            if runtime and runtime.isdigit() and int(runtime) > 0:
                m["runtime"] = round(int(runtime) / 60)  # seconds -> minutes
            release = ev.get("release_date") or ""
            if len(release) >= 4 and release[:4].isdigit():
                m["year"] = release[:4]

        _set(user_id, stage="Matching movies", done=0, total=len(movies))
        for n, (name, m) in enumerate(movies.items(), 1):
            _set(user_id, done=n)
            if ("film", name.lower()) in existing_titles:
                summary["skipped"] += 1
                continue
            found = _search_movie(name, m["year"])
            tmdb_id = found["id"] if found else None
            final_title = ((found or {}).get("title") or name).strip()
            if (tmdb_id and ("film", tmdb_id) in existing_tmdb
                    or ("film", final_title.lower()) in existing_titles):
                summary["skipped"] += 1
                continue
            if not found:
                summary["unmatched"].append(name)
            release = (found or {}).get("release_date") or ""
            item = MediaItem(
                user_id=user_id,
                media_type=MediaType.film,
                title=final_title,
                year=int(release[:4]) if release[:4].isdigit()
                else (int(m["year"]) if m["year"] else None),
                status=WatchStatus.completed if m["watched"]
                else WatchStatus.want_to_watch,
                tmdb_id=tmdb_id,
                runtime_minutes=m["runtime"],
                poster_url=f"{POSTER_BASE}{found['poster_path']}"
                if found and found.get("poster_path") else None,
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
            except IntegrityError:
                summary["skipped"] += 1
                continue
            existing_titles.add(("film", final_title.lower()))
            if tmdb_id:
                existing_tmdb.add(("film", tmdb_id))
            summary["movies"] += 1
            if n % 50 == 0:
                db.commit()
        db.commit()

        summary["unmatched"] = summary["unmatched"][:20]
        _set(user_id, stage="Done", finished=True, summary=summary, error=None)
    except Exception as exc:
        db.rollback()
        _set(user_id, stage="Failed", finished=True, error=str(exc), summary=summary)
    finally:
        db.close()


@router.post("/tvtime", status_code=status.HTTP_202_ACCEPTED)
async def import_tvtime(
    file: UploadFile,
    user: User = Depends(get_current_user),
):
    running = _progress.get(user.id)
    if running and not running.get("finished", True):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="An import is already running")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail="File too large")
    try:
        zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="That is not a zip file")
    _progress[user.id] = {"stage": "Starting", "done": 0, "total": 0,
                          "finished": False, "error": None, "summary": None}
    threading.Thread(target=_run_import, args=(user.id, data), daemon=True).start()
    return {"status": "started"}


@router.get("/tvtime/status")
def import_status(user: User = Depends(get_current_user)):
    return _progress.get(user.id) or {"stage": "Never run", "finished": True,
                                      "error": None, "summary": None,
                                      "done": 0, "total": 0}
