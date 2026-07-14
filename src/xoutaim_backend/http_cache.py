#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/13 09:45:00.000000
Revised: 2026/07/13 09:45:00.000000

Small in-memory TTL cache for read-only external API responses (TMDB, Open
Library, YouTube Data API). Per-process, not persisted — tmdb_store.py is the
place for anything that needs to survive a restart.
"""

import time


class TTLCache:
    def __init__(self, ttl_seconds: float, max_entries: int):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._data: dict[tuple, tuple[float, object]] = {}

    def get(self, key: tuple):
        hit = self._data.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        return None

    def put(self, key: tuple, value: object) -> None:
        """Insert with eviction so the cache can't grow without bound."""
        if len(self._data) >= self.max_entries:
            now = time.time()
            for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                del self._data[k]
            while len(self._data) >= self.max_entries:  # still full: drop oldest-expiring
                del self._data[min(self._data, key=lambda k: self._data[k][0])]
        self._data[key] = (time.time() + self.ttl_seconds, value)
