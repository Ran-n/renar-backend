#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:25:14.175174
Revised: 2026/07/21 09:51:05.098938

Premium feature rules: the color palette users may pick from and the
derivation of the "flair" (badge + colors) every user payload carries.

The palette is server-defined and validated on write so a client can never
store an arbitrary hex value: every option stays readable on both the light
and the dark theme. The frontend fetches it from GET /premium/palette
instead of duplicating the list.
"""

from typing import Literal, get_args

from .. import site_settings
from ..models import User

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


# Mirrors the frontend's THEMES dict in renar_frontend/themes.py — keep the
# two in sync. Only "gruvbox" is free; the rest require an active subscription.
FREE_THEMES: frozenset[str] = frozenset({"gruvbox"})
THEME_NAMES: frozenset[str] = FREE_THEMES | frozenset({
    "gruvbox_hard",
    "gruvbox_soft",
    "gruvbox_light",
    "midnight",
    "light",
    "nord",
    "dracula",
    "solarized_light",
    "catppuccin",
})


# Home screen "continue watching" progress indicator style. Only "rings" is
# free; "capsule" and "chips" require an active subscription, same gate as
# non-free themes (enforced in the /auth/profile route, not here).
FREE_PROGRESS_STYLES: frozenset[str] = frozenset({"rings"})
PROGRESS_STYLES: frozenset[str] = FREE_PROGRESS_STYLES | frozenset({"capsule", "chips"})


# Season/episode label format shown next to episode titles. Only "cross"
# ("1×05") is free; "standard" (localized S/E-style abbreviation, e.g.
# "T01E05" where the local word for season starts with T), "literal" (always
# the English "S01E05", regardless of language) and "verbose" ("Season 1 ·
# Episode 5") require an active subscription, same gate as theme/progress
# style (enforced in the /auth/profile route, not here).
FREE_EPISODE_LABEL_STYLES: frozenset[str] = frozenset({"cross"})
EPISODE_LABEL_STYLES: frozenset[str] = FREE_EPISODE_LABEL_STYLES | frozenset({"standard", "literal", "verbose"})


# One admin-toggleable perk each; the site_settings column for a given
# name is f"premium_{name}_enabled" (see SiteSettings in models.py).
PremiumFeature = Literal["style", "verification", "background", "themes", "progress_style", "episode_label", "ranking"]
PREMIUM_FEATURES: tuple[str, ...] = get_args(PremiumFeature)


def feature_enabled(feature: PremiumFeature) -> bool:
    """Whether the admin has this specific premium perk switched on
    site-wide, independent of any individual user's subscription."""
    return getattr(site_settings.current(), f"premium_{feature}_enabled")


def premium_active(user: User, feature: PremiumFeature) -> bool:
    """Whether this user should get the given premium perk right now —
    both an unexpired subscription and that perk's admin toggle must hold."""
    return user.is_premium and feature_enabled(feature)


def flair(user: User) -> dict:
    """Badge + effective colors for public payloads (comments, profiles,
    feed). Colors are served only while premium is active — the stored
    choice survives a lapse but stops rendering everywhere.
    """
    active = premium_active(user, "style")
    return {
        "badge": user.badge,
        "ring_color": user.ring_color if active else None,
        "name_color": user.name_color if active else None,
        "background": user.background if active else None,
    }
