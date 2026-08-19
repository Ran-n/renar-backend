#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000

TVDB subpackage: HTTP client with auth (tvdb_http) and the fetch/shape
helpers for the import fallback path (tvdb_store) — mirrors tmdb/'s split,
one tier down in richness. See users/tvtime_import.py's module docstring
and docs/design-decisions.md for why TVDB exists as a real fallback here,
not just a name source.
"""
