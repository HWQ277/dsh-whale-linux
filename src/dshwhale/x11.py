"""X11 window shaping and stacking via ctypes.

The widget is a frameless, always-on-top floating whale. Three X11 facilities
make that work, and none of them need a compositor:

``SHAPE``
    ``XShapeCombineMask`` clips the window to a 1-bit silhouette so the area
    around the whale and its speech bubble shows the desktop instead of a grey
    box. We also set the *input* shape to the same silhouette, which means the
    transparent margins do not swallow clicks.

    If the server refuses the shape (or the user turns masking off) the widget
    falls back to painting the sprite pre-blended onto the window background
    colour, which still looks deliberate rather than broken.

``_NET_WM_STATE_ABOVE`` / ``_NET_WM_WINDOW_TYPE``
    Ask the window manager to keep the widget above normal windows and out of
    the taskbar, the same intent as ``alwaysOnTop`` + ``skipTaskbar``.

Everything here is best-effort: a missing ``libX11``/``libXext`` or an
unsupported request disables the feature instead of crashing the widget.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from typing import Iterable, Sequence

__all__ = ["X11", "ShapeMask", "X11Unavailable"]


class X11Unavailable(Exception):
    """Raised when libX11/libXext cannot be used."""


class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


# SHAPE kinds
SHAPE_BOUNDING = 0
SHAPE_CLIP = 1
SHAPE_INPUT = 2
# SHAPE ops
SHAPE_SET = 0
SHAPE_UNION = 1

# EWMH atoms we care about
_NET_WM_STATE = b"_NET_WM_STATE"
_NET_WM_STATE_ABOVE = b"_NET_WM_STATE_ABOVE"
_NET_WM_STATE_SKIP_TASKBAR = b"_NET_WM_STATE_SKIP_TASKBAR"
_NET_WM_STATE_SKIP_PAGER = b"_NET_WM_STATE_SKIP_PAGER"
_NET_WM_STATE_STICKY = b"_NET_WM_STATE_STICKY"
_NET_WM_WINDOW_TYPE = b"_NET_WM_WINDOW_TYPE"
_NET_WM_WINDOW_TYPE_DOCK = b"_NET_WM_WINDOW_TYPE_DOCK"
_NET_WM_WINDOW_TYPE_UTILITY = b"_NET_WM_WINDOW_TYPE_UTILITY"


class ShapeMask:
    """A 1-bit silhouette bitmap, built from an alpha channel."""

    __slots__ = ("width", "height", "stride", "data")

    def __init__(self, width: int, height: int, data: bytes) -> None:
        self.width = width
        self.height = height
        self.stride = (width + 7) // 8
        self.data = data

    @classmethod
    def from_alpha(
        cls,
        width: int,
        height: int,
        alpha: bytes | bytearray,
        threshold: int = 100,
    ) -> "ShapeMask":
        """Build a mask from a per-pixel alpha buffer (LSB-first X bitmap)."""
        stride = (width + 7) // 8
        data = bytearray(stride * height)
        for y in range(height):
            row = y * width
            base = y * stride
            for x in range(width):
                if alpha[row + x] >= threshold:
                    data[base + (x >> 3)] |= 1 << (x & 7)
        return cls(width, height, bytes(data))

    @classmethod
    def from_flags(cls, width: int, height: int, flags: Sequence[bool]) -> "ShapeMask":
        stride = (width + 7) // 8
        data = bytearray(stride * height)
        for y in range(height):
            base = y * stride
            row = y * width
            for x in range(width):
                if flags[row + x]:
                    data[base + (x >> 3)] |= 1 << (x & 7)
        return cls(width, height, bytes(data))


class X11:
    """Thin, defensive wrapper around the handful of Xlib calls we need."""

    def __init__(self) -> None:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise X11Unavailable("没有 DISPLAY：当前不是图形会话")
        self._lib = self._load()
        self.display = self._lib.XOpenDisplay(None)
        if not self.display:
            raise X11Unavailable("XOpenDisplay 失败")
        self._atoms: dict[bytes, int] = {}
        self._shape_ok = self._probe_shape()

    # ------------------------------------------------------------- loading
    @staticmethod
    def _load():
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        ext = ctypes.util.find_library("Xext") or "libXext.so.6"
        try:
            lib = ctypes.CDLL(name)
            lib.Xext = ctypes.CDLL(ext)
        except OSError as exc:
            raise X11Unavailable(f"无法加载 X11 库: {exc}") from exc

        void_p, ulong, cint, cuint = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint

        lib.XOpenDisplay.restype = void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XCloseDisplay.argtypes = [void_p]
        lib.XFlush.argtypes = [void_p]
        lib.XSync.argtypes = [void_p, ctypes.c_int]
        lib.XFree.argtypes = [void_p]
        lib.XInternAtom.restype = ulong
        lib.XInternAtom.argtypes = [void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XQueryTree.restype = cint
        lib.XQueryTree.argtypes = [
            void_p, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong),
            ctypes.POINTER(ctypes.POINTER(ulong)), ctypes.POINTER(cuint),
        ]
        lib.XCreateBitmapFromData.restype = ulong
        lib.XCreateBitmapFromData.argtypes = [void_p, ulong, ctypes.c_char_p, cuint, cuint]
        lib.XFreePixmap.argtypes = [void_p, ulong]
        lib.XGetWindowProperty.restype = cint
        lib.XGetWindowProperty.argtypes = [
            void_p, ulong, ulong, ctypes.c_long, ctypes.c_long, cint, ulong,
            ctypes.POINTER(ulong), ctypes.POINTER(cint), ctypes.POINTER(ulong),
            ctypes.POINTER(ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        lib.XDisplayWidth.restype = cint
        lib.XDisplayWidth.argtypes = [void_p, cint]
        lib.XDisplayHeight.restype = cint
        lib.XDisplayHeight.argtypes = [void_p, cint]
        lib.XGetGeometry.restype = cint
        lib.XGetGeometry.argtypes = [
            void_p, ulong, ctypes.POINTER(ulong), ctypes.POINTER(cint), ctypes.POINTER(cint),
            ctypes.POINTER(cuint), ctypes.POINTER(cuint), ctypes.POINTER(cuint),
            ctypes.POINTER(cuint),
        ]
        lib.XChangeProperty.restype = cint
        lib.XChangeProperty.argtypes = [
            void_p, ulong, ulong, ulong, cint, cint, ctypes.c_char_p, cint
        ]

        ext_lib = lib.Xext
        ext_lib.XShapeCombineMask.restype = None
        ext_lib.XShapeCombineMask.argtypes = [void_p, ulong, cint, cint, cint, ulong, cint]
        ext_lib.XShapeCombineRectangles.restype = None
        ext_lib.XShapeCombineRectangles.argtypes = [
            void_p, ulong, cint, cint, cint,
            ctypes.POINTER(_XRectangle), cint, cint, cint,
        ]
        ext_lib.XShapeQueryExtension.restype = cint
        ext_lib.XShapeQueryExtension.argtypes = [void_p, ctypes.POINTER(cint), ctypes.POINTER(cint)]
        return lib

    def _probe_shape(self) -> bool:
        try:
            event, error = ctypes.c_int(), ctypes.c_int()
            return bool(
                self._lib.Xext.XShapeQueryExtension(
                    self.display, ctypes.byref(event), ctypes.byref(error)
                )
            )
        except Exception:
            return False

    # --------------------------------------------------------------- atoms
    @property
    def shape_available(self) -> bool:
        return self._shape_ok

    def atom(self, name: bytes) -> int:
        cached = self._atoms.get(name)
        if cached is None:
            cached = int(self._lib.XInternAtom(self.display, name, 0))
            self._atoms[name] = cached
        return cached

    # ----------------------------------------------------------- discovery
    def toplevel_of(self, window: int) -> int:
        """Walk up from a Tk window id to the managed top-level window."""
        cur = int(window)
        seen = set()
        for _ in range(16):
            if cur in seen:
                break
            seen.add(cur)
            parent = ctypes.c_ulong()
            root = ctypes.c_ulong()
            children = ctypes.POINTER(ctypes.c_ulong)()
            count = ctypes.c_uint()
            ok = self._lib.XQueryTree(
                self.display, ctypes.c_ulong(cur), ctypes.byref(parent),
                ctypes.byref(root), ctypes.byref(children), ctypes.byref(count),
            )
            if children:
                self._lib.XFree(children)
            if not ok or not parent.value or parent.value == cur:
                break
            cur = int(parent.value)
        return cur

    def window_chain(self, window: int) -> list[int]:
        """Return ``[window, ..., frame]`` — every window to clip.

        Tk gives us an inner window id, but what is actually *visible* is the
        wrapper frame the window manager keeps as its parent. Shaping only Tk's
        window leaves that frame painting a solid rectangle on top, which is
        exactly the "blue box" artefact. So walk all the way up (excluding the
        root window, which must never be shaped) and clip each ancestor.
        """
        root = self.root_window()
        chain: list[int] = []
        cur = int(window)
        for _ in range(16):
            if cur in chain or not cur or cur == root:
                break
            chain.append(cur)
            cur = self.parent_of(cur)
        if not chain:
            chain = [int(window)]
        return chain

    def root_window(self) -> int:
        """The screen's root window (never shaped)."""
        if not hasattr(self, "_root_window"):
            self._lib.XDefaultRootWindow.restype = ctypes.c_ulong
            self._lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self._root_window = int(self._lib.XDefaultRootWindow(self.display))
        return self._root_window

    def parent_of(self, window: int) -> int:
        """Parent window id, or 0 when ``window`` is already top-level."""
        parent = ctypes.c_ulong()
        root = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        ok = self._lib.XQueryTree(
            self.display, ctypes.c_ulong(int(window)), ctypes.byref(root),
            ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count),
        )
        if children:
            self._lib.XFree(children)
        if not ok:
            return 0
        value = int(parent.value)
        return 0 if value == int(window) else value

    # -------------------------------------------------------------- shape
    def apply_shape(self, window: int, mask: ShapeMask, *, kinds: Iterable[int] = (SHAPE_BOUNDING, SHAPE_CLIP)) -> bool:
        """Clip ``window`` and its ancestor frames to ``mask``. Returns success.

        Only BOUNDING and CLIP are set. Shaping the *input* region to the same
        silhouette looks tidier on paper, but it makes every click outside the
        whale/bubble art fall through to the desktop — including right-clicks on
        the bubble, which is how the menu is opened. Leaving the input region as
        the full rectangle keeps the widget reliably clickable.
        """
        if not self._shape_ok:
            return False
        try:
            # XCreateBitmapFromData needs a real drawable of depth 1; the window
            # we are about to shape is the natural choice.
            chain = self.window_chain(window)
            pixmap = self._lib.XCreateBitmapFromData(
                self.display, ctypes.c_ulong(chain[0]), mask.data, mask.width, mask.height
            )
            if not pixmap:
                return False
            try:
                for win in chain:
                    for kind in kinds:
                        self._lib.Xext.XShapeCombineMask(
                            self.display, ctypes.c_ulong(win), kind, 0, 0,
                            ctypes.c_ulong(pixmap), SHAPE_SET,
                        )
                self.flush()
            finally:
                self._lib.XFreePixmap(self.display, ctypes.c_ulong(pixmap))
            return True
        except Exception:
            return False

    def reset_shape(self, window: int) -> None:
        """Remove any clip so the full rectangle is visible again."""
        if not self._shape_ok:
            return
        try:
            for win in self.window_chain(window):
                for kind in (SHAPE_BOUNDING, SHAPE_CLIP, SHAPE_INPUT):
                    self._lib.Xext.XShapeCombineMask(
                        self.display, ctypes.c_ulong(win), kind, 0, 0, 0, SHAPE_SET
                    )
            self.flush()
        except Exception:
            pass

    # ------------------------------------------------------------ stacking
    def set_above(self, window: int, above: bool = True, *, sticky: bool = True, skip_taskbar: bool = True) -> bool:
        """Ask the WM to keep the widget above normal windows."""
        if not above and not skip_taskbar:
            return False
        try:
            state = self.atom(_NET_WM_STATE)
            xa_atom = 4  # XA_ATOM
            values: list[int] = []
            if above:
                values.append(self.atom(_NET_WM_STATE_ABOVE))
            if skip_taskbar:
                values.append(self.atom(_NET_WM_STATE_SKIP_TASKBAR))
                values.append(self.atom(_NET_WM_STATE_SKIP_PAGER))
            if sticky:
                values.append(self.atom(_NET_WM_STATE_STICKY))
            if not values:
                return False
            payload = (ctypes.c_ulong * len(values))(*values)
            for win in self.window_chain(window):
                self._lib.XChangeProperty(
                    self.display, ctypes.c_ulong(win), ctypes.c_ulong(state),
                    ctypes.c_ulong(xa_atom), 32, 0,
                    ctypes.cast(payload, ctypes.c_char_p), len(values),
                )
            self.flush()
            return True
        except Exception:
            return False

    def set_window_type(self, window: int, dock: bool = False) -> bool:
        """Mark the window as a dock/utility so it stays off the taskbar."""
        try:
            kind = _NET_WM_WINDOW_TYPE_DOCK if dock else _NET_WM_WINDOW_TYPE_UTILITY
            target = self.atom(_NET_WM_WINDOW_TYPE)
            xa_atom = 4
            value = (ctypes.c_ulong * 1)(self.atom(kind))
            for win in self.window_chain(window):
                self._lib.XChangeProperty(
                    self.display, ctypes.c_ulong(win), ctypes.c_ulong(target),
                    ctypes.c_ulong(xa_atom), 32, 0,
                    ctypes.cast(value, ctypes.c_char_p), 1,
                )
            self.flush()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------- helpers
    def flush(self) -> None:
        try:
            self._lib.XFlush(self.display)
        except Exception:
            pass

    def sync(self) -> None:
        try:
            self._lib.XSync(self.display, 0)
        except Exception:
            pass

    # ------------------------------------------------------------- struts
    def panel_rects(self) -> list[tuple[int, int, int, int]]:
        """Bounding boxes of screen-edge dock/panel windows, in root coords.

        A left-docked widget that lands on top of a panel shows the panel's
        colour through its transparent areas, which looks like a coloured
        background behind the whale. Detecting the panels lets the widget snap
        clear of them instead.

        Two signals are used, both cheap and crash-free:
        ``_NET_WM_WINDOW_TYPE_DOCK``, and "sliver hugging a screen edge" which
        catches panels that do not advertise the type.
        """
        rects: list[tuple[int, int, int, int]] = []
        try:
            root = self.root_window()
            screen_w = self._screen_width()
            screen_h = self._screen_height()
            for window in self._children_of(root):
                geometry = self._absolute_geometry(window)
                if geometry is None:
                    continue
                x, y, width, height = geometry
                if width <= 1 or height <= 1:
                    continue
                if width >= screen_w - 8 and height >= screen_h - 8:
                    continue  # the desktop itself
                hugs_edge = (
                    x <= 2 or y <= 2
                    or x + width >= screen_w - 2
                    or y + height >= screen_h - 2
                )
                if not hugs_edge:
                    continue
                is_sliver = (width < 260 and height > 200) or (height < 260 and width > 200)
                if is_sliver:
                    rects.append((x, y, width, height))
        except Exception:
            pass
        return rects

    def panel_overlap(self, x: int, y: int, width: int, height: int) -> int:
        """How many pixels of the rect ``(x, y, width, height)`` a panel covers."""
        best = 0
        for px, py, pw, ph in self.panel_rects():
            ox = min(x + width, px + pw) - max(x, px)
            oy = min(y + height, py + ph) - max(y, py)
            if ox > 0 and oy > 0:
                best = max(best, ox * oy)
        return best

    def _screen_width(self) -> int:
        return int(self._lib.XDisplayWidth(self.display, ctypes.c_int(0)))

    def _screen_height(self) -> int:
        return int(self._lib.XDisplayHeight(self.display, ctypes.c_int(0)))

    def _children_of(self, window: int) -> list[int]:
        root = ctypes.c_ulong()
        parent = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        ok = self._lib.XQueryTree(
            self.display, ctypes.c_ulong(int(window)), ctypes.byref(root),
            ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count),
        )
        out: list[int] = []
        if ok and children:
            out = [int(children[i]) for i in range(count.value)]
        if children:
            self._lib.XFree(children)
        return out

    def _absolute_geometry(self, window: int) -> tuple[int, int, int, int] | None:
        """Root-relative geometry: walk up accumulating parent offsets."""
        x = y = 0
        cur = int(window)
        for _ in range(16):
            root = ctypes.c_ulong()
            parent = ctypes.c_ulong()
            children = ctypes.POINTER(ctypes.c_ulong)()
            count = ctypes.c_uint()
            ok = self._lib.XQueryTree(
                self.display, ctypes.c_ulong(cur), ctypes.byref(root),
                ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count),
            )
            if children:
                self._lib.XFree(children)
            if not ok:
                return None
            geo_root = ctypes.c_ulong()
            gx = ctypes.c_int()
            gy = ctypes.c_int()
            width = ctypes.c_uint()
            height = ctypes.c_uint()
            border = ctypes.c_uint()
            depth = ctypes.c_uint()
            if not self._lib.XGetGeometry(
                self.display, ctypes.c_ulong(cur), ctypes.byref(geo_root),
                ctypes.byref(gx), ctypes.byref(gy), ctypes.byref(width),
                ctypes.byref(height), ctypes.byref(border), ctypes.byref(depth),
            ):
                return None
            x += gx.value
            y += gy.value
            parent_id = int(parent.value)
            if parent_id == 0 or parent_id == cur or parent_id == self.root_window():
                return x, y, int(width.value), int(height.value)
            cur = parent_id
        return None
