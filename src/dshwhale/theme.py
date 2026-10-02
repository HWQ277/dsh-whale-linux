"""Colour palette, shared by the widget and the windows it opens.

Kept in its own module so ``widget.py`` and ``menu.py`` can both import it
without a circular dependency.
"""

from __future__ import annotations

#: Straight from the upstream stylesheet.
NAVY = "#203170"          # bubble outline, menu chrome, primary buttons
WHITE = "#ffffff"         # bubble fill, menu background
DANGER = "#e0433f"        # error / warning amounts
HINT = "#9fb0d9"          # secondary text (.dshwv-hint)
BUBBLE_TEXT = "#536ba9"   # .dshwv-text default colour
ROW_HOVER = "#e8ecf7"     # menu row hover
SEP_COLOUR = "#c9d2e8"    # menu separator
PANEL_BG = "#f4f6fb"      # settings window background
MUTED = "#6b7a99"         # helper text
GREEN = "#2fa24c"         # off-peak colour used by the peak module

__all__ = [
    "NAVY", "WHITE", "DANGER", "HINT", "BUBBLE_TEXT",
    "ROW_HOVER", "SEP_COLOUR", "PANEL_BG", "MUTED", "GREEN",
]
