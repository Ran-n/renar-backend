#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/11/09 16:20:34.701262

Shared numeric constants used in more than one module.

Kept here to avoid a circular import: db_triggers.py is imported by models.py,
which is imported by routers/stats.py, so db_triggers.py cannot import from
routers/stats.py.  Both db_triggers.py and routers/stats.py import from this
module instead.

Note: alembic/versions/a7c2e9f4b816_add_user_total_watch_minutes.py keeps its
own local copies of these values (_DEFAULT_FILM_RUNTIME / _DEFAULT_EPISODE_RUNTIME).
That migration's one-time backfill SQL must stay self-contained (independent of
live app code) for safe re-execution against historical schemas; do not change it.
"""

# Fallback runtime when a title's runtime_minutes is NULL in the database.
# Mirrors COALESCE(runtime_minutes, N) in the Postgres trigger SQL built by
# db_triggers.py — both must always use the same value.
DEFAULT_FILM_RUNTIME: int = 110  # minutes
DEFAULT_EPISODE_RUNTIME: int = 40  # minutes

# TMDB `status` values for shows that will not air new episodes.
ENDED_STATUSES: tuple[str, ...] = ("Ended", "Canceled")

# Platforms the in-app updater serves: one per Android ABI renar-frontend's
# launcher._ANDROID_ABIS builds. Installed apps ask for their own ABI.
APP_RELEASE_PLATFORMS: tuple[str, ...] = ("android-arm64-v8a", "android-armeabi-v7a", "android-x86_64")
# Upload cap per APK. Today's arm64 build is ~30 MB, so this leaves headroom.
APP_RELEASE_MAX_BYTES: int = 200 * 1024 * 1024
