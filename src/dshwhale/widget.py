"""The floating whale widget window.

Layout mirrors the upstream artwork: a 1026x700 speech bubble with the whale
sprite anchored in its lower-right corner, the balance in the middle of the
bubble, and "today's spend" underneath. Dragging snaps the widget to a screen
edge; snapping left mirrors the whole thing horizontally, exactly like the
original.
"""

from __future__ import annotations

import base64
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
import zlib
from pathlib import Path
from typing import Callable

from . import bubble_geom
from .balance import Balance
from .bubbles import Bubble, BubbleRenderer
from .config import Config
from .imageio import Animation, Image, flatten_on, load_animation, load_image, scale_nearest
from .menu import MenuPanel
from .ledger import Ledger, beijing_now, peak_label
from .x11 import ShapeMask, X11, X11Unavailable

# --- geometry constants (upstream proportions) -----------------------------
# The upstream widget root is a SQUARE box: width == height == base, the bubble
# is the top slice of it (aspect 1026/700) and the whale is a 59.45%-of-base
# square pinned to the bottom-right corner. Making the window only as tall as
# the bubble (the first version of this port) pushed the whale up into the
# bubble, because "bottom-right of the box" then meant "bottom of the bubble".
BASE_PX = 186.667           # reference widget size at scale == 1
BUBBLE_RATIO = 1026 / 700   # bubble aspect ratio

#: Whale image size as a fraction of the box.
#:
#: Upstream uses 0.5945, but that only works because the browser composites the
#: bubble and the whale as translucent layers. This port has no compositor, so
#: both the bubble and the whale are opaque and *whichever is drawn last wins*.
#: At 0.5945 the whale's opaque art reaches x=127,y=117 while the bubble's art
#: box is x 20..228, y 2..140 -- a 101x23px collision. When the bubble auto-hid,
#: that overlap stayed painted, so the navy "bubble" never appeared to go away.
#: 0.375 keeps the art clear of the bubble box at every scale, so hiding the
#: bubble really does clear the whole area.
SPRITE_FRACTION = 0.375
#: Upstream CSS anchors: --dshw-vx default 44.25%, --dshw-vy default 36%.
TEXT_X, TEXT_Y = 0.4425, 0.36
#: Upstream .dshwv-text is a fixed 66%-wide, 64%-tall flex box that centres its
#: content, so the text block is centred on (TEXT_X, TEXT_Y) rather than merely
#: starting there.
TEXT_BOX_W, TEXT_BOX_H = 0.66, 0.64

#: The whale PNG is transparent-padded, more on the left than elsewhere, so the
#: art is aligned to the box corner using its *opaque* bounds (measured at
#: runtime) rather than the raw image rectangle.
WHALE_ALPHA_THRESHOLD = 20

# --- colours (upstream palette, shared with menu.py) -----------------------
from .theme import BUBBLE_TEXT, DANGER, HINT, NAVY, WHITE

# --- timings ---------------------------------------------------------------
ROLL_MS = 700
BUBBLE_HIDE_MS = 5000
DRAG_THROTTLE_MS = 16
MIN_SCALE, MAX_SCALE, SCALE_STEP = 0.6, 2.5, 0.1
PRESS_MS = 110            # "Q-bounce" squash/hold time on press
IDLE_BUBBLE_MAX = 3600

#: Peak/off-peak presentation styles shown in the menu.
PEAK_LABELS = {"default": "默认", "liangwen": "梁文峰谷", "qiangqiang": "强强", "terse": "简洁"}

#: Built-in sound sets, mirroring the upstream package's SOUND_SETS mapping:
#:   duck -> Ya1/Ya2.mp3, fx1 -> D1/D2.mp3
#: ``None`` means "the user's own file in sounds/", i.e. sounds/press.mp3.
SOUND_SETS: dict[str, dict[str, str]] = {
    "duck": {"press": "duck/press.mp3", "release": "duck/release.mp3"},
    "fx1": {"press": "fx1/press.mp3", "release": "fx1/release.mp3"},
}

#: Audio players, in preference order; the first one on PATH wins.
AUDIO_PLAYERS = (
    ("paplay", ()),
    ("pw-play", ()),
    ("aplay", ("-q",)),
    ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet")),
    ("canberra-gtk-play", ("-f",)),
)

# Font fallbacks, in preference order: the widget shows CJK text.
CJK_FONTS = ("Noto Sans CJK SC", "Noto Sans CJK JP", "Source Han Sans SC",
             "WenQuanYi Micro Hei", "DejaVu Sans")


def _png_bytes(width: int, height: int, rgb: bytes) -> bytes:
    """Build a minimal RGB PNG from raw bytes (no dependencies)."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


class Sprite:
    """Loads and caches whale pixel art as Tk images."""

    def __init__(self, assets: Path) -> None:
        self.assets = assets
        self._raw_cache: dict[str, Image] = {}
        self._photo_cache: dict[tuple, tk.PhotoImage] = {}

    def clear(self) -> None:
        """Drop cached decodes/Photos (used when the role image changes)."""
        self._raw_cache.clear()
        self._photo_cache.clear()

    def raw(self, name: str) -> Image:
        image = self._raw_cache.get(name)
        if image is None:
            image = load_image(str(self.assets / name))
            self._raw_cache[name] = image
        return image

    def photo(self, master: tk.Misc, name: str, size: int, background: tuple[int, int, int],
              mirrored: bool = False) -> tk.PhotoImage:
        key = (id(master), name, size, background, mirrored)
        cached = self._photo_cache.get(key)
        if cached is not None:
            return cached
        scaled = scale_nearest(self.raw(name), size, size)
        if mirrored:
            scaled = self._mirror(scaled)
        rgb = flatten_on(scaled, background)
        photo = tk.PhotoImage(master=master, data=base64.b64encode(_png_bytes(size, size, rgb)))
        self._photo_cache[key] = photo
        return photo

    @staticmethod
    def _mirror(image: Image) -> Image:
        out = bytearray(len(image.pixels))
        w, h = image.width, image.height
        for y in range(h):
            row = y * w * 4
            for x in range(w):
                src = row + (w - 1 - x) * 4
                dst = row + x * 4
                out[dst : dst + 4] = image.pixels[src : src + 4]
        return Image(w, h, out)


class WhaleWidget:
    """The always-on-top whale window."""

    def __init__(self, config: Config, assets: Path, on_quit: Callable[[], None] | None = None) -> None:
        self.config = config
        self.assets = assets
        self.on_quit = on_quit or (lambda: None)
        self.ledger = Ledger(config.usage)

        self.root = tk.Tk()
        self.root.title("DeepSeek 小鲸鱼")
        self.root.overrideredirect(True)
        self.root.configure(bg=NAVY)
        self.root.attributes("-topmost", bool(config.get("alwaysOnTop", True)))
        try:
            self.root.wm_attributes("-type", "dock")
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg=NAVY)
        self.canvas.pack(fill="both", expand=True)

        self.sprites = Sprite(assets)
        # The font must be resolved before any window (menu/editors) is built.
        self.ui_font = self._pick_font()
        self.menu = MenuPanel(self.root, self.ui_font, on_close=self._close_menu)
        self.anim_frames: list[tk.PhotoImage] = []
        self.anim_delays: list[int] = []

        self.x11: X11 | None
        try:
            self.x11 = X11()
        except X11Unavailable:
            self.x11 = None

        self.scale = float(config.get("scale", 1.5))
        self.size = 0
        self.box_height = 0
        self.bubble_size = 0
        self.sprite_size = 0
        self.sprite_x = 0
        self.sprite_y = 0
        self.background = self._rgb(NAVY)

        self.balance: Balance | None = None
        self.error: str | None = None
        self.shown: float | None = None
        self.bubble_open = False
        self._roll_job: str | None = None
        self._hide_job: str | None = None
        self._drag_origin: tuple[int, int, int, int] | None = None
        self._dragging = False
        self._press_xy: tuple[int, int] | None = None
        self._pending_geometry: tuple[int, int] | None = None
        self._move_job: str | None = None
        self._anim_job: str | None = None
        self._anim_index = 0
        self._menu_button_ids: list[int] = []
        self._menu_button_visible = False
        self._outside_click_bound = False
        self._settings_hint_shown = False

        self._font_cache: dict[tuple, tkfont.Font] = {}
        self._image_cache: dict[str, tk.PhotoImage] = {}
        self._squash_cache: dict[tuple, tk.PhotoImage] = {}
        #: Resolved random-line text, keyed by (line index, module index).
        #: Filled on the first draw of a display and reused for every later
        #: frame, so a 随机语句 cannot spin like a slot machine while the balance
        #: roll redraws the bubble.
        self._random_text: dict[tuple[int, int], str] = {}
        self.bubbles = BubbleRenderer(config, None)
        self._active_bubble: Bubble | None = None
        self._queue_index = 0
        self._idle_job: str | None = None
        self._squash_job: str | None = None
        self._pressed = False
        self._squash = 0.0
        self._player: tuple[str, tuple[str, ...]] | None = next(
            ((name, args) for name, args in AUDIO_PLAYERS if shutil.which(name)), None
        )
        self._build_fonts()
        self._apply_scale()
        self._bind_events()
        self._apply_stacking()
        self._show_menu_button(False)

    # ------------------------------------------------------------ utilities
    @staticmethod
    def _rgb(colour: str) -> tuple[int, int, int]:
        colour = colour.lstrip("#")
        return tuple(int(colour[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    def _pick_font(self) -> str:
        available = set(tkfont.families(self.root))
        for name in CJK_FONTS:
            if name in available:
                return name
        return "TkDefaultFont"

    def _build_fonts(self) -> None:
        unit = self.size / 1026 if self.size else 0.2
        self.font_label = tkfont.Font(root=self.root, family=self.ui_font, size=-max(7, int(unit * 62)), weight="bold")
        self.font_amount = tkfont.Font(root=self.root, family=self.ui_font, size=-max(11, int(unit * 124)), weight="bold")
        self.font_hint = tkfont.Font(root=self.root, family=self.ui_font, size=-max(7, int(unit * 52)))
        self.font_period = tkfont.Font(root=self.root, family=self.ui_font, size=-max(8, int(unit * 74)), weight="bold")

    def _apply_scale(self) -> None:
        """Recompute the square widget box and the bubble/whale sizes inside it."""
        self._font_cache.clear()
        self._image_cache.clear()
        self._squash_cache.clear()
        self._whale_bounds = None
        size = int(round(_clamp(BASE_PX * self.scale, 150, 540)))
        self.size = size
        self.box_height = size                                   # square, as upstream
        self.bubble_height = int(round(size / BUBBLE_RATIO))     # top slice
        self.sprite_size = max(24, int(round(size * SPRITE_FRACTION)))
        # Align the whale art (not its transparent padding) to the corner.
        left, top, right, bottom = self.whale_opaque_bounds
        self.sprite_x = int(round(size - right * self.sprite_size))
        self.sprite_y = int(round(self.box_height - bottom * self.sprite_size))
        self._build_fonts()

    @property
    def role_file(self) -> str:
        """Currently selected whale art, honouring the menu's 角色 picker."""
        name = str(self.config.data.get("ui", {}).get("roleFile") or "DSniang1.png")
        return name if (self.assets / name).is_file() else "DSniang1.png"

    @property
    def whale_opaque_bounds(self) -> tuple[float, float, float, float]:
        """Opaque bounds of the whale art as fractions of the image (cached)."""
        cached = getattr(self, "_whale_bounds", None)
        if cached is None:
            image = self.sprites.raw(self.role_file)
            width, height = image.width, image.height
            x0 = y0 = None
            x1 = y1 = 0
            alpha = image.pixels[3::4]
            for y in range(height):
                row = y * width
                for x in range(width):
                    if alpha[row + x] > WHALE_ALPHA_THRESHOLD:
                        if x0 is None or x < x0:
                            x0 = x
                        if x > x1:
                            x1 = x
                        if y0 is None:
                            y0 = y
                        y1 = y
            if x0 is None:  # fully transparent art: fall back to the whole image
                x0, y0, x1, y1 = 0, 0, width - 1, height - 1
            cached = (x0 / width, y0 / height, (x1 + 1) / width, (y1 + 1) / height)
            self._whale_bounds = cached
        return cached

    # ------------------------------------------------------------- geometry
    def _target_geometry(self) -> tuple[int, int]:
        """Resolve the stored anchor/position into a top-left screen position."""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width, height = self.size, self.box_height
        pos = self.config.pos
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            h_anchor = pos.get("hAnchor") or "right"
            v_anchor = pos.get("vAnchor") or "bottom"
            margin = max(8, int(self.size * 0.04))
            x = margin if h_anchor == "left" else screen_w - width - margin
            y = margin if v_anchor == "top" else screen_h - height - margin
        return int(x), int(y)

    def _place_window(self) -> None:
        x, y = self._target_geometry()
        x, y = self._avoid_panels(x, y, self.size, self.box_height,
                                  self.root.winfo_screenwidth())
        self.root.geometry(f"{self.size}x{self.box_height}+{x}+{y}")

    # ---------------------------------------------------------------- build
    def _bind_events(self) -> None:
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-3>", self._on_context)
        c.bind("<Enter>", lambda _e: self._show_menu_button(True))
        c.bind("<Leave>", lambda _e: self._maybe_hide_menu_button())
        self.root.bind("<Escape>", lambda _e: self.menu.close())

    # ------------------------------------------------------------- painting
    def _sprite_photo_for(self, size: int, mirrored: bool) -> tk.PhotoImage:
        """The whale image, squashed if a press animation is in flight.

        The squash keeps the bottom edge anchored (matching the upstream "press
        the doll" feel) by shrinking the source vertically before scaling back up
        to ``size`` and padding the missing rows below.
        """
        if self._squash <= 0.001:
            return self.sprites.photo(self.root, self.role_file, size, self.background, mirrored)
        cache_key = (size, mirrored, round(self._squash, 3))
        cached = self._squash_cache.get(cache_key)
        if cached is not None:
            return cached
        import math as _math

        strength = _math.sin(self._squash * _math.pi * 0.5)
        source = self.sprites.raw(self.role_file)
        keep = max(0.25, 1.0 - 0.18 * strength)
        grow = 1.0 + 0.16 * strength
        sw, sh = source.width, source.height
        crop_h = max(4, int(sh * keep))
        crop_w = max(4, int(sw / grow))
        x0 = max(0, (sw - crop_w) // 2)
        y0 = max(0, sh - crop_h)
        cropped = Image(crop_w, crop_h, bytearray(
            b"".join(
                source.pixels[((y0 + y) * sw + x0) * 4 : ((y0 + y) * sw + x0 + crop_w) * 4]
                for y in range(crop_h)
            )
        ))
        scaled = scale_nearest(cropped, size, size)
        # Push the scaled art down so its bottom edge stays put.
        shifted = Image(size, size, bytearray(size * size * 4))
        offset = size - max(1, int(size * keep))
        for y in range(offset, size):
            src_y = y - offset
            if src_y >= size:
                break
            dst = y * size * 4
            src = src_y * size * 4
            shifted.pixels[dst : dst + size * 4] = scaled.pixels[src : src + size * 4]
        if mirrored:
            shifted = Sprite._mirror(shifted)
        rgb = flatten_on(shifted, self.background)
        photo = tk.PhotoImage(
            master=self.root,
            data=base64.b64encode(_png_bytes(size, size, rgb)),
        )
        if len(self._squash_cache) > 48:
            self._squash_cache.clear()
        self._squash_cache[cache_key] = photo
        return photo

    def _render(self) -> None:
        """Redraw the whole widget."""
        c = self.canvas
        c.delete("all")
        self._menu_button_ids = []

        sprite_size = self.sprite_size
        mirrored = bool(self.config.pos.get("hAnchor") == "left")
        # Mirrored (docked left) puts the whale in the bottom-left corner and
        # flips the art, matching the upstream widget's scaleX(-1) behaviour.
        # sprite_x/sprite_y already align the art's opaque box to the corner.
        sx = (self.size - self.sprite_x - sprite_size) if mirrored else self.sprite_x
        sy = self.sprite_y

        # 1. whale sprite (optionally squashed by the press animation)
        photo = self._sprite_photo_for(sprite_size, mirrored)
        c.create_image(sx, sy, image=photo, anchor="nw")
        self._sprite_photo = photo  # keep a reference alive

        # 2. speech bubble
        if self.bubble_open:
            self._draw_bubble(mirrored)

        # 3. menu button
        if self._menu_button_visible and not self.config.data.get("ui", {}).get("menuButtonHidden"):
            self._draw_menu_button(mirrored)

    def _scaled_contour(self, contour: list[tuple[float, float]], mirrored: bool) -> list[float]:
        """Map a normalised contour into canvas coordinates."""
        w, h = self.size, self.bubble_height
        points: list[float] = []
        for nx, ny in contour:
            x = (1.0 - nx) * w if mirrored else nx * w
            points.append(x)
            points.append(ny * h)
        return points

    def _draw_bubble(self, mirrored: bool) -> None:
        c = self.canvas
        outer = [self._scaled_contour(contour, mirrored) for contour in bubble_geom.OUTER]
        inner = [self._scaled_contour(contour, mirrored) for contour in bubble_geom.INNER]

        for points in outer:
            c.create_polygon(points, fill=NAVY, outline=NAVY, width=1)
        for points in inner:
            c.create_polygon(points, fill=WHITE, outline=WHITE, width=1)

        self._draw_bubble_content(mirrored)

    # ------------------------------------------------------- bubble content
    def _template_values(self) -> dict[str, str]:
        """Live values for ``{balance}``-style placeholders."""
        currency = self.balance.currency if self.balance else (self.ledger.currency or "CNY")
        balance = self._format(self.shown, plain=True)
        today = self._format(self.ledger.today_usage, plain=True)
        status = peak_label()
        return {
            # Upstream names (see the comment block above bubbleAmountText).
            "balance_ds": balance,
            "expense_ds": today,
            "status": status,
            "countdown": self._peak_countdown(),
            "session": "当前对话",
            "quota": "--", "quota_used": "--", "quota_left": "--",
            "quota_total": "--", "quota_reset": "--",
            "plan": "--", "plan_left": "--", "plan_reset": "--",
            "cost": "--", "amount": balance,
            # Friendly aliases kept for hand-written configs.
            "balance": balance,
            "today": today,
            "peak": status,
            "currency": currency,
            "name": "小鲸鱼",
        }

    def _peak_countdown(self) -> str:
        """``{countdown}`` -> time until the next peak/off-peak switch."""
        from .ledger import next_transition

        _label, when = next_transition()
        delta = when - beijing_now()
        seconds = max(0, int(delta.total_seconds()))
        hours, minutes = divmod(seconds // 60, 60)
        return f"{hours}:{minutes:02d}"

    def _font_for(self, size: int, bold: bool = False, italic: bool = False,
                  underline: bool = False) -> tkfont.Font:
        key = (size, bold, italic, underline)
        font = self._font_cache.get(key)
        if font is None:
            font = tkfont.Font(root=self.root, family=self.ui_font, size=-max(7, int(size)),
                               weight="bold" if bold else "normal",
                               slant="italic" if italic else "roman",
                               underline=1 if underline else 0)
            self._font_cache[key] = font
        return font

    def _default_module_size(self) -> int:
        """Fallback module size level (upstream palette default)."""
        from .bubbles import SIZE_DEFAULT

        return SIZE_DEFAULT

    def _module_px(self, level: int, unit: float, fallback_level: int) -> int:
        """Convert a module size level (1..50) into pixels.

        Mirrors upstream: ``bubbleModuleFontU(level)`` gives a CSS unit multiple,
        and the font renders at ``that * (base / 1026)`` pixels. Only a floor is
        applied here; genuine overflow is handled by the per-line shrink below.
        """
        from .bubbles import font_units

        units = font_units(level or fallback_level)
        return max(8, int(round(units * unit)))

    def _draw_bubble_content(self, mirrored: bool) -> None:
        """Render the active bubble: its lines, modules and any image."""
        bubble = self._active_bubble
        cx = (1.0 - TEXT_X) * self.size if mirrored else TEXT_X * self.size
        centre_y = TEXT_Y * self.bubble_height
        values = self._template_values()

        # Error state replaces the whole bubble with a short diagnostic.
        if self.error:
            self._draw_error_content(cx, centre_y, mirrored)
            return
        if bubble is None:
            return

        # Upstream lays the text out in a fixed box: 66% of the widget wide and
        # 64% of the bubble tall, centred on the anchor. Mirroring that keeps line
        # spacing identical to the web widget instead of drifting with content.
        max_inner_width = self.size * TEXT_BOX_W

        images = self.bubbles.image_modules(bubble)
        if images:
            self._draw_bubble_image(images[0], centre_y, mirrored)
            # Text lines, if any, sit under the image.
            centre_y += self.bubble_height * 0.30

        # Resolve lines, then measure so the block can be centred vertically.
        #
        # The random pick is SNAPSHOT for the whole display: _render() runs many
        # times per bubble (the balance roll alone is 28 frames), and re-picking
        # on every frame made a 随机语句 module flicker through sentences like a
        # slot machine before settling. A new tap clears the snapshot.
        unit = self.size / 1026.0   # upstream --dshw-u
        resolved: list[tuple[list[tuple[str, Any]], int, int]] = []
        default_size = self._default_module_size()
        for line_index, line in enumerate(bubble.lines):
            runs = self.bubbles.resolve_line(
                line, values, cache=self._random_text, line_index=line_index)
            if not runs:
                continue
            max_size = max(self._module_px(m.size, unit, default_size) for _text, m in runs)
            width = 0
            for text, module in runs:
                font = self._font_for(self._module_px(module.size, unit, default_size),
                                      module.bold, module.italic, module.underline)
                width += font.measure(text)
            gap = max(3, int(max_size * 0.34)) * max(0, len(runs) - 1)
            resolved.append((runs, width + gap, max_size))
        if not resolved:
            return

        total = sum(int(sz * 1.34) for _r, _w, sz in resolved)
        # Upstream's flex box is 64% of the bubble tall (and taller than the
        # visible bubble interior, so real content has room). Only genuinely
        # oversized content is scaled down, per line, keeping proportion.
        max_inner_height = self.bubble_height * TEXT_BOX_H
        vscale = min(1.0, max_inner_height / total) if total > max_inner_height else 1.0
        if vscale < 1.0:
            resolved = [(runs, width, max(8, int(sz * vscale))) for runs, width, sz in resolved]
            total = sum(int(sz * 1.34) for _r, _w, sz in resolved)
        y = centre_y - total / 2
        for runs, width, max_size in resolved:
            line_height = int(max_size * 1.34)
            # Never let a line spill outside the bubble's inner box.
            shrink = min(1.0, max_inner_width / width) if width > max_inner_width else 1.0
            x = cx - (width * shrink) / 2
            for text, module in runs:
                size = self._module_px(module.size, unit, default_size)
                if shrink < 1.0:
                    size = max(7, int(size * shrink))
                font = self._font_for(size, module.bold, module.italic, module.underline)
                run_width = font.measure(text)
                self.canvas.create_text(
                    x + run_width / 2, y + line_height / 2, text=text, font=font,
                    fill=module.colour or BUBBLE_TEXT, anchor="center",
                )
                x += run_width + max(3, int(size * 0.34))
            y += line_height

    def _draw_error_content(self, cx: float, centre_y: float, mirrored: bool) -> None:
        default_size = self._default_module_size()
        # Same wording as upstream: "获取失败 · 点击重试" as the hint row.
        lines = [
            ("获取失败", int(default_size * 1.0), BUBBLE_TEXT, False),
            (self._format(self.shown), int(default_size * 1.94), DANGER, True),
            ("点击重试", int(default_size * 0.85), HINT, False),
        ]
        heights = [int(sz * 1.34) for _t, sz, _c, _b in lines]
        y = centre_y - sum(heights) / 2
        for (text, size, colour, bold), height in zip(lines, heights):
            font = self._font_for(size, bold)
            self.canvas.create_text(cx, y + height / 2, text=text, font=font,
                                    fill=colour, anchor="center")
            y += height

    def _draw_bubble_image(self, name: str, centre_y: float, mirrored: bool) -> None:
        """Draw an image module inside the bubble, scaled to fit."""
        photo = self._bubble_image(name)
        if photo is None:
            return
        cx = (1.0 - TEXT_X) * self.size if mirrored else TEXT_X * self.size
        self.canvas.create_image(cx, centre_y - self.bubble_height * 0.04,
                                 image=photo, anchor="center")

    def _bubble_image(self, name: str) -> tk.PhotoImage | None:
        """Load (and cache) a bubble image, scaling it to fit the bubble."""
        cached = self._image_cache.get(name)
        if cached is not None:
            return cached
        path = self.assets / name
        if not path.is_file():
            return None
        try:
            max_w = int(self.size * 0.60)
            max_h = int(self.bubble_height * 0.46)
            if path.suffix.lower() == ".gif":
                animation = load_animation(str(path))
                first = animation.frames[0]
                scale = min(max_w / first.width, max_h / first.height, 1.0)
                width = max(1, int(first.width * scale))
                height = max(1, int(first.height * scale))
                rgb = flatten_on(scale_nearest(first, width, height), self._rgb(WHITE))
                photo = tk.PhotoImage(
                    master=self.root,
                    data=base64.b64encode(_png_bytes(width, height, rgb)),
                )
            else:
                image = load_image(str(path))
                scale = min(max_w / image.width, max_h / image.height, 1.0)
                width = max(1, int(image.width * scale))
                height = max(1, int(image.height * scale))
                rgb = flatten_on(scale_nearest(image, width, height), self._rgb(WHITE))
                photo = tk.PhotoImage(
                    master=self.root,
                    data=base64.b64encode(_png_bytes(width, height, rgb)),
                )
        except (OSError, ValueError):
            return None
        self._image_cache[name] = photo
        return photo

    def _draw_menu_button(self, mirrored: bool) -> None:
        c = self.canvas
        top = 0.4055 * self.bubble_height + 4
        size = 26
        x = 4 if mirrored else self.size - size - 4
        tag_ids = c.create_rectangle(x, top, x + size, top + size, fill="#203170", outline="")
        for i in range(3):
            y = top + 7 + i * 6
            c.create_line(x + 6, y, x + size - 6, y, fill=WHITE, width=2)
        self._menu_button_ids = [tag_ids]
        c.tag_bind(tag_ids, "<Button-1>", self._on_menu_click)

    def _format(self, value: float | None, *, plain: bool = False) -> str:
        """Format an amount. ``plain`` drops the currency symbol for templates."""
        if value is None:
            return "…"
        text = f"{value:,.2f}"
        if plain:
            return text
        currency = self.balance.currency if self.balance else (self.ledger.currency or "CNY")
        return f"¥ {text}" if currency == "CNY" else f"{text} {currency}"

    # --------------------------------------------------------------- shape
    def _apply_mask(self) -> None:
        """Clip the window to the whale + bubble silhouette."""
        if self.x11 is None or not self.config.get("maskEnabled", True):
            self._render()
            return
        try:
            width, height = self.size, self.box_height
            flags = [False] * (width * height)
            # Defined before the branch: it used to live inside `if bubble_open`
            # and the whale branch below then raised UnboundLocalError, which the
            # bare except swallowed -- leaving an EMPTY mask that clipped the
            # whole widget away whenever the bubble was closed.
            mirrored = bool(self.config.pos.get("hAnchor") == "left")

            # bubble silhouette from the traced contours (point-in-polygon scanline)
            if self.bubble_open:
                for contour in bubble_geom.OUTER:
                    points = self._scaled_contour(contour, mirrored)
                    self._fill_polygon(flags, width, height, points)

            # whale silhouette from its alpha channel
            sprite_size = self.sprite_size
            sprite = scale_nearest(self.sprites.raw(self.role_file), sprite_size, sprite_size)
            ox = (self.size - self.sprite_x - sprite_size) if mirrored else self.sprite_x
            oy = self.sprite_y
            alpha = sprite.pixels[3::4]
            for y in range(sprite_size):
                canvas_y = oy + y
                if not (0 <= canvas_y < height):
                    continue
                base = canvas_y * width
                row = y * sprite_size
                for x in range(sprite_size):
                    if alpha[row + x] < 100:
                        continue
                    canvas_x = ox + x
                    if 0 <= canvas_x < width:
                        flags[base + canvas_x] = True

            mask = ShapeMask.from_flags(width, height, flags)
            ok = self.x11.apply_shape(self.root.winfo_id(), mask)
            if not ok:
                self.x11.reset_shape(self.root.winfo_id())
            self._render()
        except Exception as exc:
            # Surface the reason instead of silently drawing an empty widget.
            print(f"[dsh-whale] 异形窗口掩码失败，已退化为矩形卡片: {exc!r}", file=sys.stderr)
            self._render()

    @staticmethod
    def _fill_polygon(flags: list[bool], width: int, height: int, points: list[float]) -> None:
        """Scanline-fill a polygon into a boolean buffer."""
        count = len(points) // 2
        if count < 3:
            return
        ys = points[1::2]
        y_min = max(0, int(math.floor(min(ys))))
        y_max = min(height - 1, int(math.ceil(max(ys))))
        for y in range(y_min, y_max + 1):
            scan = y + 0.5
            crossings: list[float] = []
            for i in range(count):
                j = (i + 1) % count
                y1, y2 = points[i * 2 + 1], points[j * 2 + 1]
                if (y1 <= scan < y2) or (y2 <= scan < y1):
                    x1, x2 = points[i * 2], points[j * 2]
                    crossings.append(x1 + (scan - y1) * (x2 - x1) / (y2 - y1))
            crossings.sort()
            base = y * width
            for k in range(0, len(crossings) - 1, 2):
                x_start = max(0, int(math.ceil(crossings[k] - 0.5)))
                x_end = min(width - 1, int(math.floor(crossings[k + 1] - 0.5)))
                for x in range(x_start, x_end + 1):
                    flags[base + x] = True

    # ---------------------------------------------------------- interaction
    def _widget_at_pointer(self) -> bool:
        try:
            px, py = self.root.winfo_pointerxy()
            x, y = self.root.winfo_x(), self.root.winfo_y()
            return x <= px < x + self.size and y <= py < y + self.box_height
        except tk.TclError:
            return False

    def _on_press(self, event: tk.Event) -> None:
        self._press_xy = (event.x, event.y)
        self._dragging = False
        self._pressed = True
        self._press_animation()
        self._play("press")
        self._drag_origin = (
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        ox, oy, wx, wy = self._drag_origin
        dx, dy = event.x_root - ox, event.y_root - oy
        if not self._dragging and abs(dx) + abs(dy) < 5:
            return
        self._dragging = True
        self._pending_geometry = (wx + dx, wy + dy)
        if self._move_job is None:
            self._move_job = self.root.after(DRAG_THROTTLE_MS, self._flush_move)

    def _flush_move(self) -> None:
        """Apply the pending drag position, cancelling any queued frame first.

        Cancelling matters: without it the previously scheduled ``after``
        callback still fires and re-applies the *older* position, which made
        the window snap back to where the drag started.
        """
        if self._move_job is not None:
            try:
                self.root.after_cancel(self._move_job)
            except (tk.TclError, ValueError):
                pass
            self._move_job = None
        if self._pending_geometry is None:
            return
        x, y = self._pending_geometry
        self._pending_geometry = None
        self.root.geometry(f"{self.size}x{self.box_height}+{int(x)}+{int(y)}")

    def _on_release(self, event: tk.Event) -> None:
        was_dragging = self._dragging
        self._dragging = False
        self._drag_origin = None
        self._press_xy = None
        if self._pressed:
            self._pressed = False
            self._release_animation()
            self._play("release")
        if was_dragging:
            self._snap()
        else:
            # A plain tap only drives the bubble sequence. It deliberately does
            # NOT refresh the balance: doing so changed `shown`, which kicked off
            # the 28-frame roll animation and made the bubble look like a slot
            # machine spinning through values. Balance stays on its own 60s
            # timer, plus 立即刷新余额 in the menu.
            self.tap_advance()

    def _on_context(self, event: tk.Event) -> None:
        self._show_menu(event.x_root, event.y_root)

    def _on_menu_click(self, _event: tk.Event) -> None:
        self._show_menu(self.root.winfo_x() + self.size - 120, self.root.winfo_y() + int(self.bubble_height * 0.45))

    def _snap(self) -> None:
        """Snap to the nearest horizontal edge and mirror when on the left."""
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w, h = self.size, self.box_height

        if self.config.get("snapOn", True):
            centre_x = x + w / 2
            centre_y = y + h / 2
            if centre_x < width / 4:
                x, h_anchor = 0, "left"
            elif centre_x > width * 3 / 4:
                x, h_anchor = width - w, "right"
            else:
                h_anchor = None
            if centre_y < height / 4:
                y, v_anchor = 0, "top"
            elif centre_y > height * 3 / 4:
                y, v_anchor = height - h, "bottom"
            else:
                v_anchor = None
            if h_anchor:
                self.config.pos["hAnchor"] = h_anchor
            if v_anchor:
                self.config.pos["vAnchor"] = v_anchor

        x = int(_clamp(x, 0, max(0, width - w)))
        y = int(_clamp(y, 0, max(0, height - h)))
        x, y = self._avoid_panels(x, y, w, h, width)
        self.config.pos["x"] = x
        self.config.pos["y"] = y
        self.config.save()
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._apply_mask()

    def _avoid_panels(self, x: int, y: int, w: int, h: int, screen_w: int) -> tuple[int, int]:
        """Move the widget off any desktop panel it would otherwise sit on.

        The widget is transparent by design, so wherever it overlaps a panel you
        see the *panel's* colour through it -- a blue block behind the whale on a
        default XFCE panel theme. Sliding clear leaves the window transparent to
        the wallpaper, which is what the widget should look like.

        Both axes are adjusted, because a full-width top panel spans every x and
        so cannot be escaped horizontally.
        """
        if self.x11 is None or not self.config.get("avoidPanels", True):
            return x, y
        try:
            if self.x11.panel_overlap(x, y, w, h) <= 0:
                return x, y
            screen_h = self.root.winfo_screenheight()
            xs: list[int] = []
            ys: list[int] = []
            for px, py, pw, ph in self.x11.panel_rects():
                # Horizontal escape, for side panels.
                if pw < screen_w * 0.8:
                    if x < px + pw <= x + w:
                        xs.append(px + pw + 4)
                    if px < x + w and px >= x:
                        xs.append(px - w - 4)
                # Vertical escape, for top/bottom panels.
                if ph < screen_h * 0.8:
                    if y < py + ph <= y + h:
                        ys.append(py + ph + 4)
                    if py < y + h and py >= y:
                        ys.append(py - h - 4)

            def clear(cx: int, cy: int) -> bool:
                return self.x11.panel_overlap(cx, cy, w, h) <= 0

            for cx in sorted(xs, key=lambda c: abs(c - x)):
                cx = int(_clamp(cx, 0, max(0, screen_w - w)))
                if cx != x and clear(cx, y):
                    return cx, y
            for cy in sorted(ys, key=lambda c: abs(c - y)):
                cy = int(_clamp(cy, 0, max(0, screen_h - h)))
                if cy != y and clear(x, cy):
                    return x, cy
            # Neither axis alone is enough: try the combinations.
            for cx in sorted(xs, key=lambda c: abs(c - x)):
                for cy in sorted(ys, key=lambda c: abs(c - y)):
                    cx2 = int(_clamp(cx, 0, max(0, screen_w - w)))
                    cy2 = int(_clamp(cy, 0, max(0, screen_h - h)))
                    if clear(cx2, cy2):
                        return cx2, cy2
        except Exception:
            pass
        return x, y

    # ------------------------------------------------------------- popup UI
    def _show_menu_button(self, visible: bool) -> None:
        if self.config.data.get("ui", {}).get("menuButtonHidden"):
            visible = False
        if visible == self._menu_button_visible:
            return
        self._menu_button_visible = visible
        self._render()
        self._apply_mask()

    def _maybe_hide_menu_button(self) -> None:
        if self.menu.open:
            return
        self._show_menu_button(False)

    # ------------------------------------------------------------ main menu
    def _menu_scale_number(self, scale: float) -> int:
        """Map scale -> the 1..20 number shown next to the slider.

        Straight from upstream: ``min + (n-1) * (max-min) / 19``.
        """
        if MAX_SCALE == MIN_SCALE:
            return 1
        ratio = (scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)
        return max(1, min(20, int(round(1 + ratio * 19))))

    def _scale_from_number(self, number: int) -> float:
        number = max(1, min(20, int(number)))
        return MIN_SCALE + (number - 1) * (MAX_SCALE - MIN_SCALE) / 19

    def _close_menu(self) -> None:
        self.menu.close()
        self._render()

    def _show_menu(self, x: int, y: int) -> None:
        """Build the menu with the upstream widget's exact rows and wording.

        Row order follows the upstream ``menuBox.appendChild`` sequence:
        角色 / 大小 / 音效与提示 / 气泡全局开关 / 避让滚动条 / 吸附与翻转 /
        隐藏菜单按钮 / 资源管理.
        """
        panel = self.menu
        panel.build()
        bubbles = self.bubbles.data

        # --- 角色 (role picker + import) ------------------------------------
        self.var_role = tk.StringVar(value=self._current_role_name())
        role_row = panel.row(title="角色")
        panel.dropdown(role_row, self._current_role_name(), self._role_choices(), width=8)
        panel.button(role_row, "导入", self._import_role, primary=False)

        # --- 大小 (slider + 1..20 number) ----------------------------------
        self.var_scale = tk.DoubleVar(value=self.scale)
        self.var_scale_num = tk.IntVar(value=self._menu_scale_number(self.scale))
        size_row = panel.row(title="大小")
        slider = tk.Scale(
            size_row, from_=MIN_SCALE, to=MAX_SCALE, resolution=0.1,
            orient="horizontal", variable=self.var_scale, showvalue=False,
            length=78, bg=WHITE, highlightthickness=0, bd=0, troughcolor="#c9d2e8",
            activebackground=NAVY, command=self._on_menu_scale,
        )
        slider.pack(side="left", padx=(6, 0))
        spin = tk.Spinbox(
            size_row, from_=1, to=20, width=3, textvariable=self.var_scale_num,
            font=(self.ui_font, 10), relief="solid", bd=1, justify="center",
            command=self._on_menu_scale_number,
        )
        spin.pack(side="left", padx=(6, 0))
        spin.bind("<Return>", lambda _e: self._on_menu_scale_number())
        spin.bind("<FocusOut>", lambda _e: self._on_menu_scale_number())

        # --- 音效与提示 (opens the sound panel) ----------------------------
        sound_row = panel.row(title="音效与提示")
        panel.button(sound_row, "全局设置", self.open_settings, primary=False).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        # --- 气泡全局开关 (+ 按压泡泡设置) ---------------------------------
        self.var_bubble_on = tk.BooleanVar(value=bool(self.config.get("bubbleOn", True)))
        bubble_row = panel.row(title="气泡全局开关")
        panel.checkbox(bubble_row, self.var_bubble_on, self._on_bubble_toggle)
        panel.button(bubble_row, "按压泡泡设置", self.open_bubble_editor).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        # --- 避让滚动条 (checkbox + width) ---------------------------------
        self.var_scroll_gap = tk.BooleanVar(value=bool(self.config.get("scrollGapOn", False)))
        self.var_scroll_gap_px = tk.IntVar(value=int(self.config.get("scrollGapPx", 17) or 17))
        gap_row = panel.row(title="避让滚动条")
        panel.checkbox(gap_row, self.var_scroll_gap, self._on_scroll_gap_toggle)
        panel.label("宽度", parent=gap_row).pack(side="left", padx=(6, 0))
        self.scroll_gap_spin = tk.Spinbox(
            gap_row, from_=0, to=200, width=4, textvariable=self.var_scroll_gap_px,
            font=(self.ui_font, 10), relief="solid", bd=1, justify="center",
            command=self._on_scroll_gap_px,
        )
        self.scroll_gap_spin.pack(side="left", padx=(4, 0))
        self.scroll_gap_spin.configure(
            state="normal" if self.var_scroll_gap.get() else "disabled")
        panel.label("px", parent=gap_row).pack(side="left", padx=(4, 0))

        panel.separator()

        # --- 吸附与翻转 ----------------------------------------------------
        snap_row = panel.row(title="吸附与翻转")
        panel.button(snap_row, "自定义", self.open_snap_settings).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        # --- 隐藏菜单按钮 --------------------------------------------------
        self.var_menu_hidden = tk.BooleanVar(
            value=bool(self.config.data.get("ui", {}).get("menuButtonHidden")))
        hide_row = panel.row(title="隐藏菜单按钮")
        panel.checkbox(hide_row, self.var_menu_hidden, self._on_menu_hidden_toggle)

        # --- 资源管理 ------------------------------------------------------
        res_row = panel.row(title="资源管理")
        panel.button(res_row, "管理", self.open_resources).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        # --- 底部：记账 / 退出（上游的导航行等价物） -----------------------
        panel.separator()
        nav = panel.row()
        panel.button(nav, "退出小鲸鱼", self.quit).pack(side="left", fill="x", expand=True)

        # Park the panel's bottom edge 6px above the whale artwork, exactly like
        # upstream (artwork occupies the bottom 59.45% of the square root box).
        root_y = self.root.winfo_y()
        asset_top = root_y + self.box_height - int(self.box_height * SPRITE_FRACTION)
        align = "left" if self.config.pos.get("hAnchor") == "left" else "right"
        panel.show(self.root, above=asset_top - 6, align=align)
        try:
            panel.window.bind("<Escape>", lambda _e: self._close_menu())
        except tk.TclError:
            pass

    # --- menu callbacks ----------------------------------------------------
    def _on_menu_scale(self, _value: str) -> None:
        self.set_scale(float(self.var_scale.get()))
        self.var_scale_num.set(self._menu_scale_number(self.scale))

    def _on_menu_scale_number(self) -> None:
        try:
            number = int(self.var_scale_num.get())
        except (tk.TclError, ValueError):
            return
        self.set_scale(self._scale_from_number(number))

    def _on_bubble_toggle(self) -> None:
        self.config.set("bubbleOn", bool(self.var_bubble_on.get()))
        self.config.save()
        if not self.var_bubble_on.get():
            self.bubble_open = False
            self._active_bubble = None
            self._random_text = {}
            self._cancel_hide()
        self._render()
        self._apply_mask()

    def _on_scroll_gap_toggle(self) -> None:
        enabled = bool(self.var_scroll_gap.get())
        self.config.set("scrollGapOn", enabled)
        self.config.save()
        try:
            self.scroll_gap_spin.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass
        self._snap()

    def _on_scroll_gap_px(self) -> None:
        try:
            value = max(0, min(200, int(self.var_scroll_gap_px.get())))
        except (tk.TclError, ValueError):
            return
        self.config.set("scrollGapPx", value)
        self.config.save()
        self._snap()

    def _on_menu_hidden_toggle(self) -> None:
        ui = self.config.data.setdefault("ui", {})
        ui["menuButtonHidden"] = bool(self.var_menu_hidden.get())
        self.config.save()
        self._show_menu_button(False)

    # --- role picker -------------------------------------------------------
    def _current_role_name(self) -> str:
        return str(self.config.data.get("ui", {}).get("roleName") or "小鲸鱼")

    def _role_choices(self) -> list[tuple[str, Callable[[], None]]]:
        choices = [("小鲸鱼", lambda: self._set_role("DSniang1.png", "小鲸鱼"))]
        if (self.assets / "DSniang02.png").is_file():
            choices.append(("小鲸鱼 02", lambda: self._set_role("DSniang02.png", "小鲸鱼 02")))
        for extra in sorted((self.assets / "roles").glob("*.png")) if (self.assets / "roles").is_dir() else []:
            choices.append((extra.stem, lambda name=extra.name, stem=extra.stem: self._set_role(f"roles/{name}", stem)))
        return choices

    def _set_role(self, filename: str, label: str) -> None:
        ui = self.config.data.setdefault("ui", {})
        ui["roleFile"] = filename
        ui["roleName"] = label
        self.config.save()
        self.sprites.clear()
        self._whale_bounds = None
        self._render()
        self._apply_mask()

    def _import_role(self) -> None:
        """Import a custom whale image into the assets/roles folder."""
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            parent=self.root, title="选择角色图片",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
        )
        if not path:
            return
        target_dir = self.assets / "roles"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            import shutil as _shutil

            name = Path(path).name
            _shutil.copyfile(path, target_dir / name)
        except OSError as exc:
            messagebox.showerror("小鲸鱼", f"导入失败：{exc}", parent=self.root)
            return
        self._set_role(f"roles/{name}", Path(path).stem)

    # --- other menu targets ------------------------------------------------
    def open_snap_settings(self) -> None:
        from .settings import SnapSettingsWindow

        SnapSettingsWindow(self)

    def open_resources(self) -> None:
        from .settings import ResourceManagerWindow

        ResourceManagerWindow(self)

    def open_bubble_editor(self) -> None:
        from .bubble_editor import BubbleEditorWindow

        BubbleEditorWindow(self)

    def _toggle_setting(self, key: str) -> None:
        self._set_setting(key, not bool(self.config.get(key, True)))

    def _toggle_bubble_flag(self, key: str) -> None:
        data = self.bubbles.data
        data[key] = not bool(data.get(key, True))
        self.config.save()
        self._render()

    def _toggle_mask(self) -> None:
        enabled = not bool(self.config.get("maskEnabled", True))
        self.config.set("maskEnabled", enabled)
        self.config.save()
        if not enabled and self.x11 is not None:
            # Drop any existing clip, otherwise turning masking "off" would
            # leave the window shaped until the next restart.
            self.x11.reset_shape(self.root.winfo_id())
        self._render()
        self._apply_mask()

    def cycle_peak_style(self) -> None:
        order = ["default", "liangwen", "qiangqiang", "terse"]
        data = self.bubbles.data
        current = str(data.get("peakStyle") or "default")
        try:
            index = order.index(current)
        except ValueError:
            index = 0
        data["peakStyle"] = order[(index + 1) % len(order)]
        self.config.save()
        self._render()

    def _set_setting(self, key: str, value) -> None:
        self.config.set(key, value)
        self.config.save()
        self._render()

    def _set_ui(self, key: str, value) -> None:
        self.config.data.setdefault("ui", {})[key] = value
        self.config.save()
        self._render()

    def _nudge_scale(self, delta: float) -> None:
        self.set_scale(self.scale + delta)

    def set_scale(self, value: float) -> None:
        self.scale = _clamp(round(value, 2), MIN_SCALE, MAX_SCALE)
        self.config.set("scale", self.scale)
        self.config.save()
        self._apply_scale()
        self._place_window()
        self._render()
        self.root.after(30, self._apply_mask)

    def toggle_bubble(self) -> None:
        self.bubble_open = not self.bubble_open
        self._render()
        self._apply_mask()

    def open_settings(self) -> None:
        from .settings import SettingsWindow

        SettingsWindow(self)

    # ------------------------------------------------------- balance/refresh
    def _render_bubble_if_open(self) -> None:
        """Redraw after new data, but only if a bubble is already showing."""
        if self.bubble_open:
            self._render()
            self._apply_mask()
        elif self.error is None:
            self._render()

    def _cancel_hide(self) -> None:
        if self._hide_job is not None:
            try:
                self.root.after_cancel(self._hide_job)
            except (tk.TclError, ValueError):
                pass
            self._hide_job = None

    def _open_bubble(self, bubble: "Bubble | None" = None) -> None:
        """Pop a bubble out, unless the user disabled automatic bubbles.

        ``bubble=None`` means "show the balance", i.e. the first item of the
        click sequence. A pending auto-hide from a previous reading is cancelled
        so it cannot close the bubble we are about to show.
        """
        if not self.config.get("bubbleOn", True):
            return
        if bubble is None:
            bubble = self.bubbles.bubble("first")
        if bubble is None or not bubble.lines:
            return
        self._active_bubble = bubble
        self.bubble_open = True
        # New display -> allow a fresh random pick.
        self._random_text = {}
        self._cancel_hide()
        seconds = bubble.close_after
        if seconds > 0:
            self._hide_job = self.root.after(seconds * 1000, self._auto_hide)

    def tap_advance(self) -> None:
        """A tap on the whale: roll through the bubble queue.

        With ``advanceOnTap`` on, each tap shows the next queued bubble and the
        tap after the last one closes the bubble. With it off, a tap always
        returns to the balance bubble, which is the upstream default behaviour.
        """
        if not self.config.get("bubbleOn", True):
            return
        if not self.bubbles.data.get("advanceOnTap", True):
            self._queue_index = 0
            self._open_bubble(self.bubbles.bubble("first"))
            self._render()
            self._apply_mask()
            return

        queue = self.bubbles.queue()
        first = self.bubbles.bubble("first")
        # Build the sequence: balance, then everything queued.
        sequence: list[Bubble] = []
        if first is not None:
            sequence.append(first)
        sequence.extend(queue)
        if not sequence:
            return
        if self.bubble_open:
            self._queue_index += 1
        else:
            self._queue_index = 0
        if self._queue_index >= len(sequence):
            self._queue_index = 0
            self.bubble_open = False
            self._active_bubble = None
            self._random_text = {}
            self._cancel_hide()
            self._render()
            self._apply_mask()
            return
        self._open_bubble(sequence[self._queue_index])
        self._render()
        self._apply_mask()

    def _idle_bubble(self) -> None:
        """Float an idle bubble out on a timer (independent of clicking)."""
        self._idle_job = None
        self._schedule_idle_bubble()
        if self.bubble_open or self.menu.open:
            return
        if not self.bubbles.data.get("idleOn", False):
            return
        idle = self.bubbles.data.get("idle") or []
        if not idle:
            return
        from .bubbles import Bubble as _B

        choice = random.choice(idle)
        self._open_bubble(_B.from_dict(choice) if isinstance(choice, dict) else None)
        self._render()
        self._apply_mask()

    def _schedule_idle_bubble(self) -> None:
        if self._idle_job is not None:
            try:
                self.root.after_cancel(self._idle_job)
            except (tk.TclError, ValueError):
                pass
        try:
            seconds = int(self.bubbles.data.get("idleSeconds", 0) or 0)
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0 or not self.bubbles.data.get("idleOn", False):
            self._idle_job = None
            return
        seconds = min(IDLE_BUBBLE_MAX, max(15, seconds))
        self._idle_job = self.root.after(seconds * 1000, self._idle_bubble)

    # ------------------------------------------------------------ Q-bounce
    def _set_squash(self, amount: float) -> None:
        """Squash the whale for the press animation (bottom stays put)."""
        self._squash = max(0.0, min(1.0, amount))
        self._render()

    def _press_animation(self) -> None:
        if self._squash_job is not None:
            try:
                self.root.after_cancel(self._squash_job)
            except (tk.TclError, ValueError):
                pass
        steps = 4

        def tick(index: int = 1) -> None:
            self._set_squash(index / steps)
            if index < steps:
                self._squash_job = self.root.after(PRESS_MS // steps, lambda: tick(index + 1))
            else:
                self._squash_job = None

        tick(1)

    def _release_animation(self) -> None:
        if self._squash_job is not None:
            try:
                self.root.after_cancel(self._squash_job)
            except (tk.TclError, ValueError):
                pass
        steps = 4

        def tick(index: int = steps - 1) -> None:
            self._set_squash(index / steps)
            if index > 0:
                self._squash_job = self.root.after(PRESS_MS // steps, lambda: tick(index - 1))
            else:
                self._squash = 0.0
                self._squash_job = None
                self._render()
                self._apply_mask()

        tick(steps - 1)

    # --------------------------------------------------------------- sound
    def _sound_path(self, slot: str) -> Path | None:
        """Resolve a press/release slot to a file, honouring the sound set.

        Presets mirror the upstream package (duck = 小黄鸭, fx1 = 音效1). Setting
        ``soundSet`` to anything else falls back to the user's own
        ``sounds/<slot>.mp3`` so custom files still work.
        """
        base = self.assets / "sounds"
        preset = SOUND_SETS.get(str(self.config.get("soundSet") or "duck"))
        candidates: list[Path] = []
        if preset and slot in preset:
            candidates.append(base / preset[slot])
        candidates.append(base / f"{slot}.mp3")
        candidates.append(base / f"{slot}.wav")
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _play(self, slot: str) -> None:
        """Play a press/release sound in the background (best effort)."""
        if not self.config.get("sound", True) or self._player is None:
            return
        path = self._sound_path(slot)
        if path is None:
            return
        program, extra = self._player
        try:
            subprocess.Popen(
                [program, *extra, str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            pass

    def refresh(self, manual: bool = False) -> None:
        """Fetch the balance on a worker thread and update the UI."""
        import threading

        from .balance import fetch_balance

        key = self.config.api_key
        if not key:
            self.error = "未配置 API Key · 右键 → 设置"
            self._render_bubble_if_open()
            self._first_run_hint()
            return

        def worker() -> None:
            result = fetch_balance(key)
            try:
                self.root.after(0, lambda: self._on_balance(result))
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=worker, daemon=True, name="balance").start()

    def _first_run_hint(self) -> None:
        """With no API key configured, open settings once so setup is obvious."""
        if self._settings_hint_shown or self.config.key_from_env:
            return
        self._settings_hint_shown = True
        self.root.after(400, self.open_settings)

    def _on_balance(self, result) -> None:
        from .balance import Balance as BalanceResult
        from .balance import BalanceError

        if isinstance(result, BalanceError):
            # A transient hiccup keeps showing the last known balance.
            if result.transient and self.balance is not None:
                self.error = None
                self._render()
                return
            self.error = result.message
            if self.shown is None:
                self.shown = self.ledger.last_balance()
            # Only refresh an already-open bubble; never force one open.
            self._render_bubble_if_open()
            return

        assert isinstance(result, BalanceResult)
        previous = self.shown
        self.balance = result
        self.error = None
        self.ledger.update(result.total, result.currency)
        self.config.save()

        if previous is not None and abs(previous - result.total) > 1e-9 and self.bubble_open:
            self._start_roll(previous, result.total)
        else:
            self.shown = result.total
            self._render_bubble_if_open()

    def _start_roll(self, start: float, end: float) -> None:
        """Animate the balance from ``start`` to ``end`` (cubic ease-out)."""
        if self._roll_job is not None:
            try:
                self.root.after_cancel(self._roll_job)
            except (tk.TclError, ValueError):
                pass
            self._roll_job = None
        self._open_bubble()
        steps = 28
        interval = max(16, ROLL_MS // steps)

        def tick(index: int = 0) -> None:
            progress = min(1.0, index / steps)
            eased = 1 - (1 - progress) ** 3
            self.shown = start + (end - start) * eased
            self._render()
            if progress < 1.0:
                self._roll_job = self.root.after(interval, lambda: tick(index + 1))
            else:
                self.shown = end
                self._roll_job = None
                self._render()
                self._apply_mask()

        self._apply_mask()
        tick(0)

    def _auto_hide(self) -> None:
        self._hide_job = None
        if self.bubble_open and not self.menu.open:
            self.bubble_open = False
            self._random_text = {}
            self._render()
            self._apply_mask()

    # ---------------------------------------------------------- window mgmt
    def _apply_stacking(self) -> None:
        if self.x11 is None:
            return
        window = self.root.winfo_id()
        self.x11.set_window_type(window, dock=True)
        self.x11.set_above(window, bool(self.config.get("alwaysOnTop", True)))

    def run(self) -> None:
        self._place_window()
        self.root.update_idletasks()
        # Bubbles are click-driven: nothing is shown until the user taps the
        # whale, so the desktop keeps a clean whale silhouette at rest.
        self._active_bubble = None
        self.bubble_open = False
        self._render()
        self.root.after(60, self._apply_mask)
        self.root.after(120, lambda: self.refresh(manual=False))
        self._schedule_refresh()
        self._schedule_idle_bubble()
        self.root.mainloop()

    def _schedule_refresh(self) -> None:
        seconds = int(self.config.get("refreshSec", 60) or 60)
        seconds = max(15, min(3600, seconds))
        self.root.after(seconds * 1000, self._tick_refresh)

    def _tick_refresh(self) -> None:
        self.refresh(manual=False)
        self._schedule_refresh()

    def quit(self) -> None:
        try:
            self.config.pos["x"] = self.root.winfo_x()
            self.config.pos["y"] = self.root.winfo_y()
            self.config.save()
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.on_quit()
