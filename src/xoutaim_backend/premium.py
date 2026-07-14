#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:25:14.175174
Revised: 2026/07/13 10:27:24.306019

Premium feature rules: the color palette users may pick from and the
derivation of the "flair" (badge + colors) every user payload carries.

The palette is server-defined and validated on write so a client can never
store an arbitrary hex value: every option stays readable on both the light
and the dark theme. The frontend fetches it from GET /premium/palette
instead of duplicating the list.
"""

from .models import User

# Radix-scale step-9 accents (saturated enough to read as color on white and
# on near-black backgrounds alike), plus true black/white/grey. The frontend
# gives every ring and username render a theme-contrasting hairline/halo so
# the neutrals stay legible instead of vanishing into a same-toned surface.
PALETTE: tuple[str, ...] = (
    "#E5484D",  # red
    "#E93D82",  # crimson
    "#D6409F",  # pink
    "#AB4ABA",  # plum
    "#6E56CF",  # violet
    "#3E63DD",  # indigo
    "#0090FF",  # blue
    "#00A2C7",  # cyan
    "#12A594",  # teal
    "#46A758",  # green
    "#F76B15",  # orange
    "#FFB224",  # amber
    "#000000",  # black
    "#FFFFFF",  # white
    "#8B8D98",  # grey
)


# Mirrors the frontend's THEMES dict in xoutaim_frontend/themes.py — keep the
# two in sync. Only "gruvbox" is free; the rest require an active subscription.
FREE_THEMES: frozenset[str] = frozenset({"gruvbox"})
THEME_NAMES: frozenset[str] = FREE_THEMES | frozenset(
    {
        "gruvbox_hard",
        "gruvbox_soft",
        "gruvbox_light",
        "midnight",
        "light",
        "nord",
        "dracula",
        "solarized_light",
        "catppuccin",
    }
)


# Home screen "continue watching" progress indicator style. Only "rings" is
# free; "capsule" and "chips" require an active subscription, same gate as
# non-free themes (enforced in the /auth/profile route, not here).
FREE_PROGRESS_STYLES: frozenset[str] = frozenset({"rings"})
PROGRESS_STYLES: frozenset[str] = FREE_PROGRESS_STYLES | frozenset({"capsule", "chips"})


def flair(user: User) -> dict:
    """Badge + effective colors for public payloads (comments, profiles,
    feed). Colors are served only while premium is active — the stored
    choice survives a lapse but stops rendering everywhere.
    """
    active = user.is_premium
    return {
        "badge": user.badge,
        "ring_color": user.ring_color if active else None,
        "name_color": user.name_color if active else None,
        "background": user.background if active else None,
    }
