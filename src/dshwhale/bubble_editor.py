"""按压泡泡设置 — the bubble editor.

Mirrors the upstream editor's structure: a click queue (first tap, then the
queue) where each bubble is a list of lines and each line holds modules picked
from a palette. Upstream's palette is:

    文本 / 余额数值 / 今日已用 / 峰谷时段 / 时段倒计时 / 对话名
    随机语句 / 超链接 / 图片-动图 / 随机图片

Upstream edits this by drag and drop in the DOM. tkinter cannot host DOM drag
and drop, so this window uses click-to-add plus ↑/↓/删除 buttons — the same model,
a different gesture. That substitution is documented in the README.

Module *sizes* are levels 1..50, matching upstream's ``bubbleModuleFontU``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog
from typing import Any, Callable

from .bubbles import (
    BALANCE, IMAGE, LEVEL_BALANCE, LEVEL_LINK, LEVEL_NEXTPEAK, LEVEL_PEAK,
    LEVEL_SESSION, LEVEL_TEXT, LEVEL_TODAY, MAX_LINES, MAX_MODULES_PER_LINE,
    Module, PEAK, RANDOM, SIZE_MAX, SIZE_MIN, TEXT, TODAY, Bubble,
)

from .theme import MUTED, NAVY, PANEL_BG, WHITE

CARD_BG = "#ffffff"

#: Upstream palette: (key, label, factory, locked).
#: ``locked`` marks built-in value modules whose text is fixed by the program.
PALETTE: list[tuple[str, str, Callable[[], Module], bool]] = [
    ("text", "文本", lambda: Module(kind=TEXT, text="新内容", size=LEVEL_TEXT, bold=True), False),
    ("balance", "余额数值", lambda: Module(kind=BALANCE, size=LEVEL_BALANCE, text="{balance_ds}"), True),
    ("today", "今日已用", lambda: Module(kind=TODAY, size=LEVEL_TODAY, text="今日已用 {expense_ds}"), True),
    ("peak", "峰谷时段", lambda: Module(kind=PEAK, size=LEVEL_PEAK, text="{status}",
                                        colour="#e0433f"), True),
    ("nextpeak", "时段倒计时", lambda: Module(kind=PEAK, size=LEVEL_NEXTPEAK, bold=True,
                                              text="{countdown}", colour="#e0433f"), True),
    ("session", "对话名", lambda: Module(kind=TEXT, size=LEVEL_SESSION, bold=True,
                                         text="{session}"), True),
    ("random", "随机语句", lambda: Module(kind=RANDOM, size=LEVEL_TEXT, bold=True, choices=[
        ("你好呀，我是小鲸鱼～", 1.0), ("点我看看 DeepSeek 余额吧", 1.0)]), False),
    ("link", "超链接", lambda: Module(kind=TEXT, text="打开链接", size=LEVEL_LINK,
                                      colour="#2f4488", underline=True), False),
]

KIND_LABEL = {
    TEXT: "文本", BALANCE: "余额数值", TODAY: "今日已用",
    PEAK: "峰谷时段", RANDOM: "随机语句", IMAGE: "图片/动图",
}


def _describe(module: Module) -> str:
    """Short summary shown in the line list, like upstream's module chips."""
    kind = KIND_LABEL.get(module.kind, module.kind)
    if module.kind == RANDOM:
        return f"{kind}({len(module.choices)}条)" if module.choices else f"{kind}(空)"
    if module.kind == IMAGE:
        return f"{kind}: {module.image or '未选择'}"
    body = (module.text or "").strip()
    if len(body) > 16:
        body = body[:16] + "…"
    return f"{kind}: {body}" if body else kind


class BubbleEditorWindow:
    """Modal-ish editor for the click queue and each bubble's modules."""

    def __init__(self, widget) -> None:
        self.widget = widget
        self.config = widget.config
        self.font = widget.ui_font
        self.window = tk.Toplevel(widget.root)
        self.window.title("按压泡泡设置")
        self.window.configure(bg=PANEL_BG)
        self.window.geometry("760x520")
        self.window.transient(widget.root)

        # Work on a copy so 取消 really cancels.
        data = widget.bubbles.data
        self.queue: list[Bubble] = []
        first = data.get("first")
        if isinstance(first, dict):
            self.queue.append(Bubble.from_dict(first))
        for raw in (data.get("queue") or []):
            if isinstance(raw, dict):
                self.queue.append(Bubble.from_dict(raw))
        if not self.queue:
            self.queue = [Bubble()]

        self.index = 0
        self.selected_line = 0
        self.selected_module = 0
        self._build()
        self._refresh_all()

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        outer = tk.Frame(self.window, bg=PANEL_BG, padx=12, pady=10)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="点击序列", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 12, "bold")).pack(anchor="w")
        tk.Label(outer, text="第 1 项是「首次点击」的内容，之后每次点击往后推进一项；"
                            "走到最后一项再点就收起泡泡。",
                 bg=PANEL_BG, fg=MUTED, font=(self.font, 9)).pack(anchor="w", pady=(0, 6))

        body = tk.Frame(outer, bg=PANEL_BG)
        body.pack(fill="both", expand=True)

        # --- left: the click queue -------------------------------------
        left = tk.Frame(body, bg=PANEL_BG)
        left.pack(side="left", fill="y")
        tk.Label(left, text="气泡", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10, "bold")).pack(anchor="w")
        self.queue_list = tk.Listbox(left, width=20, height=14, font=(self.font, 10),
                                     exportselection=False, activestyle="none",
                                     bg=CARD_BG, fg=NAVY, relief="solid", bd=1)
        self.queue_list.pack(fill="y", expand=True)
        self.queue_list.bind("<<ListboxSelect>>", self._on_queue_select)
        qbtns = tk.Frame(left, bg=PANEL_BG)
        qbtns.pack(fill="x", pady=(4, 0))
        for text, cmd in (("＋", self._queue_add), ("↑", lambda: self._queue_move(-1)),
                          ("↓", lambda: self._queue_move(1)), ("删除", self._queue_delete)):
            tk.Button(qbtns, text=text, command=cmd, font=(self.font, 9), bg="#e8ecf7",
                      fg=NAVY, relief="solid", bd=1, padx=6, width=3).pack(side="left", padx=1)

        # --- middle: lines of the current bubble ------------------------
        mid = tk.Frame(body, bg=PANEL_BG, padx=10)
        mid.pack(side="left", fill="both", expand=True)
        tk.Label(mid, text="行（一个气泡最多 6 行）", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10, "bold")).pack(anchor="w")
        self.line_list = tk.Listbox(mid, height=14, font=(self.font, 10),
                                    exportselection=False, activestyle="none",
                                    bg=CARD_BG, fg=NAVY, relief="solid", bd=1)
        self.line_list.pack(fill="both", expand=True)
        self.line_list.bind("<<ListboxSelect>>", self._on_line_select)
        lbtns = tk.Frame(mid, bg=PANEL_BG)
        lbtns.pack(fill="x", pady=(4, 0))
        for text, cmd in (("＋行", self._line_add), ("↑", lambda: self._line_move(-1)),
                          ("↓", lambda: self._line_move(1)), ("删除行", self._line_delete)):
            tk.Button(lbtns, text=text, command=cmd, font=(self.font, 9), bg="#e8ecf7",
                      fg=NAVY, relief="solid", bd=1, padx=6).pack(side="left", padx=1)

        # --- right: modules of the selected line ------------------------
        right = tk.Frame(body, bg=PANEL_BG, padx=10)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="模块（每行最多 6 个）", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10, "bold")).pack(anchor="w")
        self.module_list = tk.Listbox(right, height=9, font=(self.font, 10),
                                      exportselection=False, activestyle="none",
                                      bg=CARD_BG, fg=NAVY, relief="solid", bd=1)
        self.module_list.pack(fill="both", expand=True)
        self.module_list.bind("<<ListboxSelect>>", self._on_module_select)

        mbtns = tk.Frame(right, bg=PANEL_BG)
        mbtns.pack(fill="x", pady=(4, 0))
        for text, cmd in (("编辑…", self._module_edit), ("样式…", self._module_style),
                          ("↑", lambda: self._module_move(-1)),
                          ("↓", lambda: self._module_move(1)),
                          ("删除", self._module_delete)):
            tk.Button(mbtns, text=text, command=cmd, font=(self.font, 9), bg="#e8ecf7",
                      fg=NAVY, relief="solid", bd=1, padx=6).pack(side="left", padx=1)

        tk.Label(right, text="可选模块（点击加入当前行）", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10, "bold")).pack(anchor="w", pady=(8, 2))
        palette = tk.Frame(right, bg=PANEL_BG)
        palette.pack(fill="x")
        for col, (_key, label, _factory, locked) in enumerate(PALETTE):
            btn = tk.Button(
                palette, text=label + ("🔒" if locked else ""),
                font=(self.font, 9), bg="#e8ecf7", fg=NAVY, relief="solid", bd=1,
                padx=6, pady=2, cursor="hand2",
                command=lambda k=_key: self._module_add(k),
            )
            btn.grid(row=col // 4, column=col % 4, sticky="ew", padx=1, pady=1)
        for col in range(4):
            palette.columnconfigure(col, weight=1)
        tk.Label(right, text="🔒 = 内置数值模块（内容由程序填充，如 {balance_ds}）",
                 bg=PANEL_BG, fg=MUTED, font=(self.font, 8)).pack(anchor="w", pady=(2, 0))

        # --- bottom actions ---------------------------------------------
        actions = tk.Frame(outer, bg=PANEL_BG)
        actions.pack(fill="x", pady=(10, 0))
        tk.Button(actions, text="恢复默认", font=(self.font, 10), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=12, command=self._restore_defaults).pack(side="left")
        tk.Button(actions, text="保存", font=(self.font, 10, "bold"), bg=NAVY, fg=WHITE,
                  relief="flat", padx=16, command=self._save).pack(side="right")
        tk.Button(actions, text="取消", font=(self.font, 10), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=12,
                  command=self.window.destroy).pack(side="right", padx=6)

    # ------------------------------------------------------- list plumbing
    @property
    def bubble(self) -> Bubble:
        return self.queue[max(0, min(self.index, len(self.queue) - 1))]

    def _refresh_all(self) -> None:
        self._refresh_queue()
        self._refresh_lines()
        self._refresh_modules()

    def _refresh_queue(self) -> None:
        self.queue_list.delete(0, "end")
        for i, bubble in enumerate(self.queue):
            mark = "首次点击" if i == 0 else f"第 {i + 1} 次点击"
            self.queue_list.insert("end", f"{mark} · {len(bubble.lines)} 行")
        if self.queue:
            self.queue_list.selection_clear(0, "end")
            self.queue_list.selection_set(self.index)

    def _refresh_lines(self) -> None:
        self.line_list.delete(0, "end")
        for i, line in enumerate(self.bubble.lines):
            summary = " + ".join(_describe(m) for m in line) or "(空行)"
            self.line_list.insert("end", f"第 {i + 1} 行: {summary}")
        if self.bubble.lines:
            self.selected_line = max(0, min(self.selected_line, len(self.bubble.lines) - 1))
            self.line_list.selection_clear(0, "end")
            self.line_list.selection_set(self.selected_line)
        else:
            self.selected_line = 0

    def _refresh_modules(self) -> None:
        self.module_list.delete(0, "end")
        line = self.current_line
        for module in line:
            self.module_list.insert("end", _describe(module))
        if line:
            self.selected_module = max(0, min(self.selected_module, len(line) - 1))
            self.module_list.selection_clear(0, "end")
            self.module_list.selection_set(self.selected_module)

    @property
    def current_line(self) -> list[Module]:
        lines = self.bubble.lines
        if not lines:
            return []
        return lines[max(0, min(self.selected_line, len(lines) - 1))]

    # ------------------------------------------------------------ handlers
    def _on_queue_select(self, _event: tk.Event) -> None:
        selection = self.queue_list.curselection()
        if selection:
            self.index = selection[0]
            self.selected_line = 0
            self.selected_module = 0
            self._refresh_lines()
            self._refresh_modules()

    def _on_line_select(self, _event: tk.Event) -> None:
        selection = self.line_list.curselection()
        if selection:
            self.selected_line = selection[0]
            self.selected_module = 0
            self._refresh_modules()

    def _on_module_select(self, _event: tk.Event) -> None:
        selection = self.module_list.curselection()
        if selection:
            self.selected_module = selection[0]

    # --- queue ops ---------------------------------------------------------
    def _queue_add(self) -> None:
        self.queue.append(Bubble(lines=[[Module(kind=TEXT, text="新内容",
                                                size=LEVEL_TEXT, bold=True)]]))
        self.index = len(self.queue) - 1
        self.selected_line = self.selected_module = 0
        self._refresh_all()

    def _queue_move(self, delta: int) -> None:
        target = self.index + delta
        if 0 <= target < len(self.queue):
            self.queue[self.index], self.queue[target] = self.queue[target], self.queue[self.index]
            self.index = target
            self._refresh_queue()

    def _queue_delete(self) -> None:
        if len(self.queue) <= 1:
            messagebox.showinfo("小鲸鱼", "至少要保留一个气泡。", parent=self.window)
            return
        del self.queue[self.index]
        self.index = max(0, self.index - 1)
        self.selected_line = self.selected_module = 0
        self._refresh_all()

    # --- line ops ----------------------------------------------------------
    def _line_add(self) -> None:
        if len(self.bubble.lines) >= MAX_LINES:
            messagebox.showinfo("小鲸鱼", f"一个气泡最多 {MAX_LINES} 行。", parent=self.window)
            return
        self.bubble.lines.append([Module(kind=TEXT, text="新内容", size=LEVEL_TEXT, bold=True)])
        self.selected_line = len(self.bubble.lines) - 1
        self.selected_module = 0
        self._refresh_lines()
        self._refresh_modules()

    def _line_move(self, delta: int) -> None:
        lines = self.bubble.lines
        target = self.selected_line + delta
        if 0 <= target < len(lines):
            lines[self.selected_line], lines[target] = lines[target], lines[self.selected_line]
            self.selected_line = target
            self._refresh_lines()
            self._refresh_modules()

    def _line_delete(self) -> None:
        lines = self.bubble.lines
        if not lines:
            return
        del lines[self.selected_line]
        self.selected_line = max(0, self.selected_line - 1)
        self._refresh_lines()
        self._refresh_modules()

    # --- module ops --------------------------------------------------------
    def _module_add(self, key: str) -> None:
        line = self.current_line
        if not line:
            messagebox.showinfo("小鲸鱼", "请先添加一行。", parent=self.window)
            return
        if len(line) >= MAX_MODULES_PER_LINE:
            messagebox.showinfo("小鲸鱼", f"每行最多 {MAX_MODULES_PER_LINE} 个模块。", parent=self.window)
            return
        factory = next((f for k, _l, f, _lk in PALETTE if k == key), None)
        if factory is None:
            return
        line.append(factory())
        self.selected_module = len(line) - 1
        self._refresh_lines()
        self._refresh_modules()

    def _module_move(self, delta: int) -> None:
        line = self.current_line
        target = self.selected_module + delta
        if 0 <= target < len(line):
            line[self.selected_module], line[target] = line[target], line[self.selected_module]
            self.selected_module = target
            self._refresh_lines()
            self._refresh_modules()

    def _module_delete(self) -> None:
        line = self.current_line
        if not line:
            return
        del line[self.selected_module]
        self.selected_module = max(0, self.selected_module - 1)
        self._refresh_lines()
        self._refresh_modules()

    def _selected_module(self) -> Module | None:
        line = self.current_line
        if not line:
            return None
        return line[max(0, min(self.selected_module, len(line) - 1))]

    def _module_edit(self) -> None:
        module = self._selected_module()
        if module is None:
            return
        if module.kind == RANDOM:
            self._edit_random(module)
            return
        text = simpledialog.askstring(
            "编辑内容", f"{KIND_LABEL.get(module.kind, module.kind)} 的内容\n"
                        f"可用占位符：{{balance_ds}} {{expense_ds}} {{status}} "
                        f"{{countdown}} {{session}}",
            initialvalue=module.text, parent=self.window,
        )
        if text is None:
            return
        module.text = text
        self._refresh_lines()
        self._refresh_modules()

    def _edit_random(self, module: Module) -> None:
        """Edit the weighted sentence pool for a 随机语句 module."""
        win = tk.Toplevel(self.window)
        win.title("随机语句")
        win.configure(bg=PANEL_BG)
        win.geometry("480x360")
        win.transient(self.window)
        tk.Label(win, text="每次显示按权重随机抽一条，不会连续重复。",
                 bg=PANEL_BG, fg=MUTED, font=(self.font, 9)).pack(anchor="w", padx=10, pady=(8, 4))
        box = tk.Frame(win, bg=PANEL_BG)
        box.pack(fill="both", expand=True, padx=10)
        rows: list[tuple[tk.Entry, tk.Entry]] = []

        def add_row(value: str = "", weight: float = 1.0) -> None:
            row = tk.Frame(box, bg=PANEL_BG)
            row.pack(fill="x", pady=2)
            entry = tk.Entry(row, font=(self.font, 10), bg=CARD_BG, fg=NAVY,
                             relief="solid", bd=1)
            entry.insert(0, value)
            entry.pack(side="left", fill="x", expand=True)
            tk.Label(row, text="权重", bg=PANEL_BG, fg=NAVY,
                     font=(self.font, 9)).pack(side="left", padx=(6, 2))
            weight_entry = tk.Entry(row, width=5, font=(self.font, 10), bg=CARD_BG,
                                    fg=NAVY, relief="solid", bd=1, justify="center")
            weight_entry.insert(0, str(weight))
            weight_entry.pack(side="left")
            rows.append((entry, weight_entry))

        for value, weight in (module.choices or [("", 1.0)]):
            add_row(value, weight)

        def on_add() -> None:
            add_row()
            win.update_idletasks()

        def on_ok() -> None:
            choices: list[tuple[str, float]] = []
            for entry, weight_entry in rows:
                text = entry.get().strip()
                if not text:
                    continue
                try:
                    weight = max(0.0, float(weight_entry.get() or 1))
                except ValueError:
                    weight = 1.0
                choices.append((text, weight))
            module.choices = choices
            win.destroy()
            self._refresh_lines()
            self._refresh_modules()

        btns = tk.Frame(win, bg=PANEL_BG)
        btns.pack(fill="x", padx=10, pady=8)
        tk.Button(btns, text="＋ 加一条", font=(self.font, 9), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=8, command=on_add).pack(side="left")
        tk.Button(btns, text="保存", font=(self.font, 10, "bold"), bg=NAVY, fg=WHITE,
                  relief="flat", padx=14, command=on_ok).pack(side="right")
        tk.Button(btns, text="取消", font=(self.font, 9), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=8,
                  command=win.destroy).pack(side="right", padx=6)

    def _module_style(self) -> None:
        """Font level / weight / slant / underline / colour / background."""
        module = self._selected_module()
        if module is None:
            return
        win = tk.Toplevel(self.window)
        win.title("模块样式")
        win.configure(bg=PANEL_BG)
        win.transient(self.window)

        var_size = tk.IntVar(value=max(SIZE_MIN, min(SIZE_MAX, module.size or LEVEL_TEXT)))
        var_bold = tk.BooleanVar(value=module.bold)
        var_italic = tk.BooleanVar(value=module.italic)
        var_underline = tk.BooleanVar(value=module.underline)
        colour = {"fg": module.colour, "bg": module.background}

        def widget_row(label: str, w: tk.Widget) -> None:
            row = tk.Frame(win, bg=PANEL_BG)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, bg=PANEL_BG, fg=NAVY, width=8, anchor="w",
                     font=(self.font, 10)).pack(side="left")
            w.pack(side="left", fill="x", expand=True)

        size_row = tk.Frame(win, bg=PANEL_BG)
        size_row.pack(fill="x", padx=12, pady=3)
        tk.Label(size_row, text="字号", bg=PANEL_BG, fg=NAVY, width=8, anchor="w",
                 font=(self.font, 10)).pack(side="left")
        scale = tk.Scale(size_row, from_=SIZE_MIN, to=SIZE_MAX, orient="horizontal",
                         variable=var_size, showvalue=True, length=200, bg=PANEL_BG,
                         highlightthickness=0, bd=0, troughcolor="#c9d2e8")
        scale.pack(side="left", fill="x", expand=True)

        flags = tk.Frame(win, bg=PANEL_BG)
        flags.pack(fill="x", padx=12, pady=3)
        for text, var in (("加粗", var_bold), ("斜体", var_italic), ("下划线", var_underline)):
            tk.Checkbutton(flags, text=text, variable=var, bg=PANEL_BG, fg=NAVY,
                           font=(self.font, 10), activebackground=PANEL_BG,
                           selectcolor=WHITE).pack(side="left", padx=(0, 10))

        def pick(kind: str) -> None:
            current = colour[kind] or "#536ba9"
            chosen = colorchooser.askcolor(color=current, parent=win, title="选择颜色")
            if chosen and chosen[1]:
                colour[kind] = chosen[1]
                preview.configure(text=f"{kind} = {chosen[1]}")

        colour_row = tk.Frame(win, bg=PANEL_BG)
        colour_row.pack(fill="x", padx=12, pady=3)
        tk.Button(colour_row, text="文字颜色", font=(self.font, 9), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=8,
                  command=lambda: pick("fg")).pack(side="left")
        tk.Button(colour_row, text="底色", font=(self.font, 9), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=8,
                  command=lambda: pick("bg")).pack(side="left", padx=6)
        tk.Button(colour_row, text="清除", font=(self.font, 9), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=8,
                  command=lambda: (colour.update({"fg": None, "bg": None}),
                                   preview.configure(text="颜色已清除"))).pack(side="left")
        preview = tk.Label(win, text="", bg=PANEL_BG, fg=MUTED, font=(self.font, 9))
        preview.pack(anchor="w", padx=12, pady=(2, 0))

        def on_ok() -> None:
            module.size = int(var_size.get())
            module.bold = bool(var_bold.get())
            module.italic = bool(var_italic.get())
            module.underline = bool(var_underline.get())
            module.colour = colour["fg"]
            module.background = colour["bg"]
            win.destroy()
            self._refresh_lines()
            self._refresh_modules()

        btns = tk.Frame(win, bg=PANEL_BG)
        btns.pack(fill="x", padx=12, pady=8)
        tk.Button(btns, text="保存", font=(self.font, 10, "bold"), bg=NAVY, fg=WHITE,
                  relief="flat", padx=14, command=on_ok).pack(side="right")
        tk.Button(btns, text="取消", font=(self.font, 9), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=8, command=win.destroy).pack(side="right", padx=6)

    # ------------------------------------------------------------- actions
    def _restore_defaults(self) -> None:
        from .bubbles import default_bubbles

        if not messagebox.askyesno("小鲸鱼", "恢复为默认序列（首次=余额，之后=今日已用/峰谷/随机语句）？",
                                   parent=self.window):
            return
        data = default_bubbles()
        self.queue = [Bubble.from_dict(data["first"])]
        self.queue += [Bubble.from_dict(item) for item in data["queue"]]
        self.index = self.selected_line = self.selected_module = 0
        self._refresh_all()

    def _save(self) -> None:
        data = self.widget.bubbles.data
        if not self.queue:
            return
        data["first"] = self.queue[0].to_dict()
        data["queue"] = [bubble.to_dict() for bubble in self.queue[1:]]
        self.config.save()
        # Re-show from the start so the edit is immediately visible.
        self.widget._queue_index = 0
        self.widget.bubble_open = False
        self.widget._active_bubble = None
        self.widget._render()
        self.widget._apply_mask()
        self.window.destroy()
