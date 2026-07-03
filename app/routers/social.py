"""Social graph: user search, profiles, follow/unfollow, activity feed."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Follow, MediaItem, User
from ..schemas import MediaItemOut

router = APIRouter(tags=["social"])


def _user_or_404(user_id: int, db: Session) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return target


def _is_following(follower_id: int, followed_id: int, db: Session) -> bool:
    return (
        db.query(Follow)
        .filter(Follow.follower_id == follower_id, Follow.followed_id == followed_id)
        .first()
        is not None
    )


def _public_user(target: User, me: User, db: Session) -> dict:
    return {
        "id": target.id,
        "username": target.username,
        "avatar": target.avatar,
        "created_at": target.created_at,
        "followers": db.query(Follow).filter(Follow.followed_id == target.id).count(),
        "following": db.query(Follow).filter(Follow.follower_id == target.id).count(),
        "items": db.query(MediaItem).filter(MediaItem.user_id == target.id).count(),
        "is_following": _is_following(me.id, target.id, db),
        "is_me": target.id == me.id,
    }


@router.get("/users/search")
def search_users(
    q: str = Query(min_length=1, max_length=50),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    users = (
        db.query(User)
        .filter(User.username.ilike(f"%{q}%"), User.id != me.id)
        .limit(20)
        .all()
    )
    return [_public_user(u, me, db) for u in users]


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return _public_user(_user_or_404(user_id, db), me, db)


@router.post("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if user_id == me.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot follow yourself"
        )
    _user_or_404(user_id, db)
    if not _is_following(me.id, user_id, db):
        db.add(Follow(follower_id=me.id, followed_id=user_id))
        db.commit()


@router.delete("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    follow = (
        db.query(Follow)
        .filter(Follow.follower_id == me.id, Follow.followed_id == user_id)
        .first()
    )
    if follow:
        db.delete(follow)
        db.commit()


@router.get("/users/{user_id}/following")
def list_following(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _user_or_404(user_id, db)
    follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
    return [_public_user(db.get(User, f.followed_id), me, db) for f in follows]


@router.get("/users/{user_id}/followers")
def list_followers(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _user_or_404(user_id, db)
    follows = db.query(Follow).filter(Follow.followed_id == user_id).all()
    return [_public_user(db.get(User, f.follower_id), me, db) for f in follows]


@router.get("/users/{user_id}/media", response_model=list[MediaItemOut])
def user_media(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _user_or_404(user_id, db)
    return (
        db.query(MediaItem)
        .filter(MediaItem.user_id == user_id)
        .order_by(MediaItem.updated_at.desc())
        .limit(100)
        .all()
    )


@router.get("/feed")
def activity_feed(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    followed_ids = [
        f.followed_id for f in db.query(Follow).filter(Follow.follower_id == me.id)
    ]
    if not followed_ids:
        return []
    entries = (
        db.query(MediaItem, User.username)
        .join(User, MediaItem.user_id == User.id)
        .filter(MediaItem.user_id.in_(followed_ids))
        .order_by(MediaItem.updated_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "user_id": item.user_id,
            "username": username,
            "item_id": item.id,
            "media_type": item.media_type.value,
            "title": item.title,
            "year": item.year,
            "poster_url": item.poster_url,
            "status": item.status.value,
            "rating": item.rating,
            "tmdb_id": item.tmdb_id,
            "episodes_watched": item.episodes_watched,
            "total_episodes": item.total_episodes,
            "updated_at": item.updated_at,
        }
        for item, username in entries
    ]
