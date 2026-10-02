"""The right-click menu, mirroring the upstream widget row for row.

Upstream builds its menu imperatively in ``assets/whale-widget.js`` as a list of
``.dshwv-menu-row`` divs. Those rows mix plain labels, checkboxes, range sliders,
number inputs, dropdown buttons and full-width action buttons, so tkinter's
``Menu`` widget cannot express it — this module draws an equivalent panel with
plain frames and binds the same behaviours.

Row order is copied from the upstream ``menuBox.appendChild`` sequence::

    角色            [小鲸鱼 ▾] [导入]
    大小            [————o————] [10]
    音效与提示      [全局设置]
    气泡全局开关    [x] [按压泡泡设置]
    避让滚动条      [ ] 宽度 [17] px
    吸附与翻转      [自定义]
    隐藏菜单按钮    [ ]
    资源管理        [管理]
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from .theme import NAVY, ROW_HOVER, SEP_COLOUR, WHITE

# --- layout (matches the upstream menu CSS) --------------------------------
MENU_W = 236          # upstream .dshwv-menu min-width:196px + 10px 12px padding
ROW_PAD_Y = 5


class MenuPanel:
    """A borderless popup panel holding upstream-style rows."""

    def __init__(self, master: tk.Misc, font_family: str, on_close: Callable[[], None]) -> None:
        self.master = master
        self.font = font_family
        self.on_close = on_close
        self.window: tk.Toplevel | None = None
        self._open_popup: tk.Toplevel | None = None
        self._dismiss_bound = False
        #: Monotonic time the menu was opened, and the pointer position that
        #: opened it. Both are used to ignore the very click that opened the
        #: menu (and any immediate trailing event), which otherwise dismissed it
        #: instantly -- that is what made right-click feel unresponsive.
        self._opened_at = 0.0
        self._opened_at_pointer: tuple[int, int] | None = None

    # ------------------------------------------------------------- lifecycle
    @property
    def open(self) -> bool:
        return self.window is not None

    def close(self) -> None:
        self.close_popup()
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None
        if self._dismiss_bound:
            for sequence in ("<Button-1>", "<Button-3>", "<FocusOut>"):
                try:
                    self.master.unbind(sequence)
                except tk.TclError:
                    pass
            self._dismiss_bound = False

    def close_popup(self) -> None:
        if self._open_popup is not None:
            try:
                self._open_popup.destroy()
            except tk.TclError:
                pass
            self._open_popup = None

    # ------------------------------------------------------------- building
    def build(self) -> tk.Toplevel:
        """Create an empty panel and return it; call :meth:`show` when done."""
        self.close()
        win = tk.Toplevel(self.master)
        self.window = win
        # Build hidden: geometry set on an unmapped Toplevel gets recomputed by
        # Tk when it maps, which made the panel balloon to its natural width.
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=NAVY)
        # Upstream: min-width 196px, max-width min(340px, 100vw-24px). The width
        # is pinned in show() once the rows are built; the height must follow the
        # content, so propagation stays on (disabling it collapsed the panel to
        # 1px tall).
        self.body = tk.Frame(win, bg=WHITE, highlightbackground=NAVY,
                             highlightthickness=1, width=MENU_W)
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self._grid_row = 0
        return win

    # ------------------------------------------------------------ row parts
    def label(self, text: str, *, colour: str = NAVY, size: int = 10,
              bold: bool = False, parent: tk.Misc | None = None) -> tk.Label:
        """A text label. Without ``parent`` it becomes its own grid row, which
        keeps inline labels from being packed into the body out of order."""
        if parent is None:
            parent = self.body
        widget = tk.Label(parent, text=text, bg=WHITE, fg=colour,
                          font=(self.font, size, "bold" if bold else "normal"))
        if parent is self.body:
            widget.grid(row=self._grid_row, column=0, sticky="w", padx=10)
            self._grid_row += 1
        return widget

    def row(self, *widgets: tk.Widget, title: str | None = None,
            gap: int = 8) -> tk.Frame:
        """One ``.dshwv-menu-row``: an optional left label plus widgets."""
        # grid, not pack: with this mix of labels/checkbuttons/sliders the packer
        # silently stopped after ~10 rows and dropped the rest of the menu.
        frame = tk.Frame(self.body, bg=WHITE, width=MENU_W - 22)
        frame.grid(row=self._grid_row, column=0, sticky="ew", padx=10, pady=ROW_PAD_Y)
        frame.grid_propagate(True)
        self._grid_row += 1
        if title is not None:
            # parent=frame: without it the label would be gridded into the body
            # and then packing it here mixes geometry managers (TclError).
            self.label(title, parent=frame).pack(side="left")
        for widget in widgets:
            widget.pack(side="left", padx=(gap, 0))
            gap = 6
        return frame

    def separator(self) -> None:
        tk.Frame(self.body, bg=SEP_COLOUR, height=1).grid(
            row=self._grid_row, column=0, sticky="ew", padx=8, pady=6)
        self._grid_row += 1

    def button(self, parent: tk.Widget, text: str, command: Callable[[], None],
               *, primary: bool = False) -> tk.Button:
        btn = tk.Button(
            parent, text=text, command=command,
            font=(self.font, 10, "bold" if primary else "normal"),
            bg=NAVY if primary else "#e8ecf7", fg=WHITE if primary else NAVY,
            relief="solid" if not primary else "flat", bd=1,
            highlightthickness=0, padx=10, pady=2, cursor="hand2",
            activebackground=ROW_HOVER, activeforeground=NAVY,
        )
        return btn

    def checkbox(self, parent: tk.Widget, variable: tk.BooleanVar,
                 command: Callable[[], None] | None = None) -> tk.Checkbutton:
        return tk.Checkbutton(
            parent, variable=variable, command=command, bg=WHITE,
            activebackground=WHITE, selectcolor=WHITE, highlightthickness=0,
            bd=0, padx=0, pady=0, cursor="hand2",
        )

    # ------------------------------------------------------------ dropdown
    def dropdown(self, parent: tk.Widget, text: str, items: list[tuple[str, Callable[[], None]]],
                 *, width: int = 10) -> tk.Button:
        """A ``[label ▾]`` button opening a small list, like their custom select."""
        btn = tk.Button(
            parent, text=f"{text} ▾", font=(self.font, 10), bg="#e8ecf7", fg=NAVY,
            relief="solid", bd=1, highlightthickness=0, padx=6, pady=2,
            cursor="hand2", width=width, anchor="w",
            activebackground=ROW_HOVER, activeforeground=NAVY,
        )
        btn.configure(command=lambda: self._toggle_list(btn, items))
        return btn

    def _toggle_list(self, anchor: tk.Button,
                     items: list[tuple[str, Callable[[], None]]]) -> None:
        if self._open_popup is not None:
            self.close_popup()
            return
        pop = tk.Toplevel(self.master)
        self._open_popup = pop
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        pop.configure(bg=NAVY)
        frame = tk.Frame(pop, bg=WHITE, highlightbackground=NAVY, highlightthickness=1)
        frame.pack(fill="both", expand=True)
        for text, command in items:
            row = tk.Label(frame, text=text, bg=WHITE, fg=NAVY, font=(self.font, 10),
                           anchor="w", padx=10, pady=4, cursor="hand2")
            row.pack(fill="x")
            row.bind("<Enter>", lambda _e, w=row: w.configure(bg=ROW_HOVER))
            row.bind("<Leave>", lambda _e, w=row: w.configure(bg=WHITE))

            def pick(_event: tk.Event, cmd: Callable[[], None] = command) -> None:
                self.close_popup()
                cmd()

            row.bind("<Button-1>", pick)
        pop.update_idletasks()
        w, h = pop.winfo_reqwidth(), pop.winfo_reqheight()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 2
        screen_h = pop.winfo_screenheight()
        if y + h > screen_h:
            y = max(0, anchor.winfo_rooty() - h - 2)
        pop.geometry(f"{max(w, 140)}x{h}+{x}+{y}")

    # ---------------------------------------------------------------- show
    def show(self, anchor: tk.Widget, *, above: int | None = None,
             align: str = "right") -> tuple[int, int, int, int]:
        """Position and reveal the panel; returns its final ``(x, y, w, h)``.

        ``above`` is the screen y the panel's bottom edge should sit at, which
        the widget computes from the sprite top (upstream parks the menu 6px
        above the whale artwork).
        """
        win = self.window
        if win is None:
            raise RuntimeError("build() first")
        # Pin the width (upstream min-width 196px) and let the height follow the
        # rows. Done while withdrawn so the geometry sticks on deiconify.
        # Sum each child's requested height plus its real pack padding. Asking
        # the body for winfo_reqheight() is unreliable before the window maps,
        # and a too-short panel silently drops the lower rows.
        # grid computes a reliable requested size, so let Tk report it.
        win.update_idletasks()
        w = MENU_W
        h = self.body.winfo_reqheight() + 2
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        root_x, root_w = anchor.winfo_rootx(), anchor.winfo_width()
        if align == "left":
            x = root_x
        else:
            x = root_x + root_w - w
        x = max(0, min(x, screen_w - w))
        top = anchor.winfo_rooty()
        if above is not None:
            y = above - h
        else:
            y = top - h
        if y < 0:
            y = min(screen_h - h, top + anchor.winfo_height() + 4)
        win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        win.deiconify()
        import time as _time
        self._opened_at = _time.monotonic()
        try:
            self._opened_at_pointer = win.winfo_pointerxy()
        except tk.TclError:
            self._opened_at_pointer = None
        win.lift()
        if not self._dismiss_bound:
            # Dismiss on a click outside the menu. Bound to the widget's own
            # windows rather than bind_all: a global binding fires BEFORE the
            # canvas handler that opens the menu, so the menu was closed again
            # immediately -- that is what made right-click feel unresponsive.
            self._dismiss_bound = True
            for sequence in ("<Button-1>", "<Button-3>"):
                self.master.bind(sequence, self._maybe_dismiss, add="+")
            on_close = self.on_close
            self.master.bind("<FocusOut>", lambda _e: on_close(), add="+")
        return int(x), int(y), w, h

    #: Ignore dismissals for this long after opening (the opening click plus any
    #: trailing ButtonRelease/press pair arrives inside this window).
    DISMISS_GRACE = 0.35

    def _maybe_dismiss(self, event: tk.Event) -> None:
        import time as _time

        if _time.monotonic() - self._opened_at < self.DISMISS_GRACE:
            return
        # The press that opened the menu (right button) must not close it either.
        if getattr(event, "num", None) == 3:
            return
        for popup in (self.window, self._open_popup):
            if popup is None:
                continue
            try:
                inside = (popup.winfo_x() <= event.x_root < popup.winfo_x() + popup.winfo_width()
                          and popup.winfo_y() <= event.y_root < popup.winfo_y() + popup.winfo_height())
            except tk.TclError:
                continue
            if inside:
                return
        self.on_close()
