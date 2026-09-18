"""Shared visual theme: a colour-blind-safe categorical palette and a stable
activity -> colour mapping used across every visual in the app."""

from __future__ import annotations

from typing import Dict, Iterable, List

# Okabe-Ito + a few extra hues; readable in light and dark.
PALETTE: List[str] = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
    "#5C6BC0", "#26A69A", "#D4A017", "#8E63CE", "#EF6C9B",
]
GHOST = "#9aa0a6"  # enabled-but-not-executed chips


def activity_colors(activities: Iterable[str]) -> Dict[str, str]:
    """Deterministic activity -> hex colour (sorted order, palette cycled)."""
    ordered = sorted(set(activities))
    return {a: PALETTE[i % len(PALETTE)] for i, a in enumerate(ordered)}


def text_on(hex_color: str) -> str:
    """Black or white, whichever contrasts better with ``hex_color``."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


__all__ = ["PALETTE", "GHOST", "activity_colors", "text_on"]
