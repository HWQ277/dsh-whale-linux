"""Settings windows.

``SettingsWindow`` is spawned from the whale's menu; ``StandaloneSettings`` is
what ``dsh-whale settings`` opens when the user has no API key yet (or just
wants to change something without the whale running).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from .balance import BalanceError, fetch_balance
from .bubbles import PEAK_STYLES, default_bubbles
from .config import Config
from .ledger import beijing_day, peak_label
from .widget import CJK_FONTS, NAVY, WHITE

PANEL_BG = "#f4f6fb"
CARD_BG = "#ffffff"
ENTRY_BG = "#ffffff"
MUTED = "#6b7a99"


def _pick_font(root: tk.Misc) -> str:
    import tkinter.font as tkfont

    available = set(tkfont.families(root))
    for name in CJK_FONTS:
        if name in available:
            return name
    return "TkDefaultFont"


class _SettingsForm:
    """Shared widgets/logic for the embedded and standalone settings windows."""

    def __init__(self, master: tk.Misc, config: Config, on_apply: Callable[[], None] | None = None) -> None:
        self.config = config
        self.on_apply = on_apply or (lambda: None)
        self.font = _pick_font(master)
        self.frame = tk.Frame(master, bg=PANEL_BG, padx=16, pady=14)
        self.frame.pack(fill="both", expand=True)

        self.var_key = tk.StringVar(value=self.config.stored_api_key or "")
        self.var_scale = tk.DoubleVar(value=float(self.config.get("scale", 1.5)))
        self.var_bubble = tk.BooleanVar(value=bool(self.config.get("bubbleOn", True)))
        self.var_today = tk.BooleanVar(value=bool(self.config.get("showTodayUsage", True)))
        self.var_snap = tk.BooleanVar(value=bool(self.config.get("snapOn", True)))
        self.var_top = tk.BooleanVar(value=bool(self.config.get("alwaysOnTop", True)))
        self.var_mask = tk.BooleanVar(value=bool(self.config.get("maskEnabled", True)))
        self.var_refresh = tk.IntVar(value=int(self.config.get("refreshSec", 60)))
        self.var_sound = tk.BooleanVar(value=bool(self.config.get("sound", True)))
        self.var_soundset = tk.StringVar(value=str(self.config.get("soundSet") or "duck"))
        bubbles = self.config.data.setdefault("bubbles", default_bubbles())
        self.var_advance = tk.BooleanVar(value=bool(bubbles.get("advanceOnTap", True)))
        self.var_peak = tk.StringVar(value=str(bubbles.get("peakStyle") or "default"))
        self.var_idle = tk.IntVar(value=int(bubbles.get("idleSeconds", 300) or 0))
        self.var_status = tk.StringVar(value="")

        self._build()

    # ------------------------------------------------------------- building
    def _label(self, text: str, row: int, bold: bool = False) -> tk.Label:
        weight = "bold" if bold else "normal"
        label = tk.Label(self.frame, text=text, bg=PANEL_BG, fg=NAVY,
                         font=(self.font, 11, weight), anchor="w")
        label.grid(row=row, column=0, sticky="w", pady=(10, 2), columnspan=2)
        return label

    def _build(self) -> None:
        f = self.frame
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=0)

        self._label("DeepSeek API Key", 0, bold=True)
        entry = tk.Entry(f, textvariable=self.var_key, show="•", font=(self.font, 10),
                         bg=ENTRY_BG, fg=NAVY, relief="solid", bd=1, width=46)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", ipady=4)
        self._entry = entry

        hint = tk.Label(
            f,
            text="留空则使用环境变量 DEEPSEEK_API_KEY。密钥保存在 "
                 f"{self.config.path}（权限 0600，base64 编码，非加密）。",
            bg=PANEL_BG, fg=MUTED, font=(self.font, 9), anchor="w", justify="left",
            wraplength=430,
        )
        hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))

        tk.Frame(f, bg="#d8dEEC", height=1).grid(row=3, column=0, columnspan=2, sticky="ew", pady=10)

        self._label("挂件大小", 4, bold=True)
        row = tk.Frame(f, bg=PANEL_BG)
        row.grid(row=5, column=0, columnspan=2, sticky="ew")
        scale = ttk.Scale(row, from_=0.6, to=2.5, variable=self.var_scale,
                          orient="horizontal", command=self._on_scale)
        scale.pack(side="left", fill="x", expand=True)
        self.lbl_scale = tk.Label(row, text=f"{self.var_scale.get():.1f}×", bg=PANEL_BG,
                                  fg=NAVY, font=(self.font, 10, "bold"), width=5)
        self.lbl_scale.pack(side="left")

        self._label("刷新间隔（秒）", 6, bold=True)
        spin = tk.Spinbox(f, from_=15, to=3600, increment=15, textvariable=self.var_refresh,
                          font=(self.font, 10), width=8, relief="solid", bd=1)
        spin.grid(row=7, column=0, sticky="w")

        self._label("显示", 8, bold=True)
        for offset, (text, var) in enumerate((
            ("自动弹出气泡", self.var_bubble),
            ("气泡显示「今日已用」", self.var_today),
            ("拖拽后吸附到屏幕边缘（贴左自动镜像翻转）", self.var_snap),
            ("窗口置顶", self.var_top),
            ("异形窗口（真正镂空鲸鱼与气泡外形）", self.var_mask),
        )):
            tk.Checkbutton(
                f, text=text, variable=var, bg=PANEL_BG, fg=NAVY, font=(self.font, 10),
                activebackground=PANEL_BG, selectcolor=WHITE, anchor="w",
            ).grid(row=9 + offset, column=0, columnspan=2, sticky="w")

        self._label("音效", 14, bold=True)
        tk.Checkbutton(
            f, text="启用音效（内置「小黄鸭」「音效1」；也可放自己的 sounds/press.mp3）",
            variable=self.var_sound, bg=PANEL_BG, fg=NAVY, font=(self.font, 10),
            activebackground=PANEL_BG, selectcolor=WHITE, anchor="w",
        ).grid(row=15, column=0, columnspan=2, sticky="w")
        soundrow = tk.Frame(f, bg=PANEL_BG)
        soundrow.grid(row=16, column=0, columnspan=2, sticky="w", pady=(2, 0))
        tk.Label(soundrow, text="音效组", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10)).pack(side="left")
        ss = tk.OptionMenu(soundrow, self.var_soundset, "duck", "fx1")
        ss.configure(font=(self.font, 10), bg="#e8ecf7", fg=NAVY, relief="solid", bd=1,
                     highlightthickness=0)
        ss.pack(side="left", padx=6)
        sspop = ss["menu"]; sspop.delete(0, "end")
        for key, label in (("duck", "小黄鸭"), ("fx1", "音效1")):
            sspop.add_command(label=label, command=lambda k=key: self.var_soundset.set(k))
        tk.Button(soundrow, text="试听", font=(self.font, 9),
                  bg="#e8ecf7", fg=NAVY, relief="solid", bd=1, padx=8,
                  command=self._test_sound).pack(side="left", padx=6)

        self._label("气泡行为", 16, bold=True)
        tk.Checkbutton(
            f, text="点一下鲸鱼＝往后推进一个气泡", variable=self.var_advance,
            bg=PANEL_BG, fg=NAVY, font=(self.font, 10), activebackground=PANEL_BG,
            selectcolor=WHITE, anchor="w",
        ).grid(row=17, column=0, columnspan=2, sticky="w")
        row_idle = tk.Frame(f, bg=PANEL_BG)
        row_idle.grid(row=18, column=0, columnspan=2, sticky="w", pady=(2, 0))
        tk.Label(row_idle, text="空闲气泡间隔（秒，0 = 关闭）", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10)).pack(side="left")
        tk.Spinbox(row_idle, from_=0, to=3600, increment=30, textvariable=self.var_idle,
                   font=(self.font, 10), width=7, relief="solid", bd=1).pack(side="left", padx=6)

        row_peak = tk.Frame(f, bg=PANEL_BG)
        row_peak.grid(row=19, column=0, columnspan=2, sticky="w", pady=(4, 0))
        tk.Label(row_peak, text="峰谷样式", bg=PANEL_BG, fg=NAVY,
                 font=(self.font, 10)).pack(side="left")
        PEAK_LABELS = {"default": "默认", "liangwen": "梁文峰谷",
                       "qiangqiang": "强强", "terse": "简洁"}
        menu = tk.OptionMenu(row_peak, self.var_peak,
                             *[k for k in PEAK_STYLES],
                             command=None)
        menu.configure(font=(self.font, 10), bg="#e8ecf7", fg=NAVY, relief="solid", bd=1,
                       highlightthickness=0)
        menu.pack(side="left", padx=6)
        # show friendly labels in the popup menu
        popup = menu["menu"]
        popup.delete(0, "end")
        for key in PEAK_STYLES:
            popup.add_command(label=PEAK_LABELS.get(key, key),
                              command=lambda k=key: self.var_peak.set(k))

        tk.Frame(f, bg="#d8dEEC", height=1).grid(row=20, column=0, columnspan=2, sticky="ew", pady=10)

        status = tk.Label(f, textvariable=self.var_status, bg=PANEL_BG, fg=MUTED,
                          font=(self.font, 9), anchor="w", justify="left", wraplength=430)
        status.grid(row=21, column=0, columnspan=2, sticky="w")

        buttons = tk.Frame(f, bg=PANEL_BG)
        buttons.grid(row=22, column=0, columnspan=2, sticky="e", pady=(12, 0))
        tk.Button(buttons, text="测试余额", font=(self.font, 10), command=self._test,
                  bg="#e8ecf7", fg=NAVY, relief="solid", bd=1, padx=10, pady=3).pack(side="left", padx=4)
        tk.Button(buttons, text="保存", font=(self.font, 10, "bold"), command=self._save,
                  bg=NAVY, fg=WHITE, relief="flat", padx=14, pady=3).pack(side="left", padx=4)

        entry.focus_set()

    def _on_scale(self, _value: str) -> None:
        self.lbl_scale.configure(text=f"{self.var_scale.get():.1f}×")

    # -------------------------------------------------------------- actions
    def _status(self, text: str) -> None:
        self.var_status.set(text)

    def _test_sound(self) -> None:
        """Play the currently selected preset so the choice is audible."""
        from .widget import SOUND_SETS
        import shutil as _shutil
        import subprocess as _sp
        from .cli import assets_dir

        preset = SOUND_SETS.get(self.var_soundset.get(), {})
        rel = preset.get("press")
        path = (assets_dir() / "sounds" / rel) if rel else None
        if path is None or not path.is_file():
            self._status("找不到该音效文件")
            return
        player = next((n for n in ("paplay", "pw-play", "aplay", "ffplay") if _shutil.which(n)), None)
        if not player:
            self._status("没有可用的音频播放器（paplay / pw-play / aplay / ffplay）")
            return
        try:
            _sp.Popen([player, str(path)], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                      start_new_session=True)
            self._status(f"正在试听 {path.name}")
        except OSError as exc:
            self._status(f"播放失败: {exc}")

    def _test(self) -> None:
        key = self.var_key.get().strip() or None
        self._status("正在测试…")
        self.frame.update_idletasks()
        result = fetch_balance(key)
        if isinstance(result, BalanceError):
            self._status(f"❌ {result.message}")
        else:
            self._status(
                f"✅ 余额 {result.fmt()}  （充值 {result.topped_up or 0:.2f} · "
                f"赠金 {result.granted or 0:.2f}）"
            )

    def _save(self) -> None:
        self.config.set_api_key(self.var_key.get().strip() or None)
        self.config.set("scale", round(float(self.var_scale.get()), 2))
        self.config.set("bubbleOn", bool(self.var_bubble.get()))
        self.config.set("showTodayUsage", bool(self.var_today.get()))
        self.config.set("snapOn", bool(self.var_snap.get()))
        self.config.set("alwaysOnTop", bool(self.var_top.get()))
        self.config.set("maskEnabled", bool(self.var_mask.get()))
        try:
            seconds = int(self.var_refresh.get())
        except (tk.TclError, ValueError):
            seconds = 60
        self.config.set("refreshSec", max(15, min(3600, seconds)))
        self.config.set("sound", bool(self.var_sound.get()))
        self.config.set("soundSet", self.var_soundset.get())
        bubbles = self.config.data.setdefault("bubbles", default_bubbles())
        bubbles["advanceOnTap"] = bool(self.var_advance.get())
        bubbles["peakStyle"] = self.var_peak.get()
        try:
            idle = int(self.var_idle.get())
        except (tk.TclError, ValueError):
            idle = 300
        bubbles["idleSeconds"] = max(0, min(3600, idle))
        self.config.save()
        self.on_apply()
        self._status("已保存 ✓")


class SettingsWindow:
    """Settings in a normal (managed) toplevel, opened from the whale menu."""

    def __init__(self, widget) -> None:
        self.widget = widget
        self.window = tk.Toplevel(widget.root)
        self.window.title("小鲸鱼设置")
        self.window.configure(bg=PANEL_BG)
        self.window.attributes("-topmost", True)
        self.window.resizable(False, False)
        self.form = _SettingsForm(self.window, widget.config, on_apply=self._apply)
        self.window.update_idletasks()
        # centre over the whale
        x = widget.root.winfo_x() - self.window.winfo_reqwidth() - 12
        y = widget.root.winfo_y()
        x = max(0, min(x, widget.root.winfo_screenwidth() - self.window.winfo_reqwidth()))
        y = max(0, min(y, widget.root.winfo_screenheight() - self.window.winfo_reqheight()))
        self.window.geometry(f"+{x}+{y}")

    def _apply(self) -> None:
        """Push settings into the live widget. Never let a UI hiccup escape."""
        widget = self.widget
        try:
            widget.scale = float(widget.config.get("scale", 1.5))
            widget.root.attributes("-topmost", bool(widget.config.get("alwaysOnTop", True)))
            widget._apply_scale()
            widget._place_window()
            widget.root.update_idletasks()
            widget._render()
            widget.root.after(40, widget._apply_mask)
        except (tk.TclError, ValueError, AttributeError):
            # The whale may be shutting down. The config is already persisted, so
            # the new settings simply take effect on next launch.
            return
        try:
            messagebox.showinfo("小鲸鱼", "设置已保存", parent=self.window)
        except tk.TclError:
            pass


class StandaloneSettings:
    """A self-contained settings window owning its own Tk root."""

    def __init__(self, config: Config, assets: Path) -> None:
        self.root = tk.Tk()
        self.root.title("DeepSeek 小鲸鱼 · 设置")
        self.root.configure(bg=PANEL_BG)
        self.root.resizable(False, False)
        font = _pick_font(self.root)

        header = tk.Frame(self.root, bg=NAVY, padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text="🐋  DeepSeek 余额小鲸鱼", bg=NAVY, fg=WHITE,
                 font=(font, 14, "bold")).pack(anchor="w")
        tk.Label(header, text="Arch Linux 桌面挂件 · 设置", bg=NAVY, fg="#9fb0d9",
                 font=(font, 9)).pack(anchor="w")

        self.form = _SettingsForm(self.root, config, on_apply=self._after_save)

        info = tk.Frame(self.root, bg=PANEL_BG, padx=16)
        info.pack(fill="x", pady=(0, 12))
        tk.Label(
            info,
            text=f"配置文件：{config.path}\n"
                 f"北京时间 {beijing_day()} · {peak_label()}\n"
                 f"素材目录:{assets}",
            bg=PANEL_BG, fg=MUTED, font=(font, 9), justify="left", anchor="w",
        ).pack(anchor="w")

        self.root.mainloop()

    def _after_save(self) -> None:
        messagebox.showinfo("小鲸鱼", "设置已保存。\n运行 dsh-whale run 启动挂件。", parent=self.root)
        self.root.destroy()


# ---------------------------------------------------------------------------
# Menu targets
# ---------------------------------------------------------------------------
class SnapSettingsWindow:
    """吸附与翻转 — where the whale sticks, and where it mirrors.

    Upstream lets you set each edge's snap zone (as a ratio or in pixels) and a
    separate flip line. This exposes the same intent with the two knobs the
    desktop widget actually uses: the snap zone fraction and whether docked-left
    mirrors the artwork.
    """

    def __init__(self, widget) -> None:
        self.widget = widget
        config = widget.config
        font = widget.ui_font
        self.window = tk.Toplevel(widget.root)
        self.window.title("吸附与翻转")
        self.window.configure(bg=PANEL_BG)
        self.window.transient(widget.root)
        self.window.resizable(False, False)

        frame = tk.Frame(self.window, bg=PANEL_BG, padx=16, pady=14)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="吸附与翻转", bg=PANEL_BG, fg=NAVY,
                 font=(font, 12, "bold")).pack(anchor="w")
        tk.Label(frame, text="拖拽松手后，鲸鱼会吸到最近的屏幕边缘。\n"
                            "贴左边时整个挂件（含文字）水平镜像翻转。",
                 bg=PANEL_BG, fg=MUTED, font=(font, 9), justify="left").pack(anchor="w", pady=(0, 8))

        self.var_snap = tk.BooleanVar(value=bool(config.get("snapOn", True)))
        self.var_zone = tk.IntVar(value=int(config.get("snapZonePct", 25) or 25))
        self.var_mirror = tk.BooleanVar(value=bool(config.get("mirrorOnLeft", True)))

        tk.Checkbutton(frame, text="启用边缘吸附", variable=self.var_snap, bg=PANEL_BG,
                       fg=NAVY, font=(font, 10), activebackground=PANEL_BG,
                       selectcolor=WHITE, anchor="w").pack(anchor="w")
        zone_row = tk.Frame(frame, bg=PANEL_BG)
        zone_row.pack(anchor="w", pady=(6, 0))
        tk.Label(zone_row, text="吸附区宽度（屏幕占比 %）", bg=PANEL_BG, fg=NAVY,
                 font=(font, 10)).pack(side="left")
        tk.Spinbox(zone_row, from_=5, to=50, width=5, textvariable=self.var_zone,
                   font=(font, 10), relief="solid", bd=1).pack(side="left", padx=6)
        tk.Checkbutton(frame, text="贴左时水平镜像翻转（原版行为）",
                       variable=self.var_mirror, bg=PANEL_BG, fg=NAVY, font=(font, 10),
                       activebackground=PANEL_BG, selectcolor=WHITE,
                       anchor="w").pack(anchor="w", pady=(6, 0))

        btns = tk.Frame(frame, bg=PANEL_BG)
        btns.pack(fill="x", pady=(12, 0))
        tk.Button(btns, text="恢复默认", font=(font, 10), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=10, command=self._reset).pack(side="left")
        tk.Button(btns, text="保存", font=(font, 10, "bold"), bg=NAVY, fg=WHITE,
                  relief="flat", padx=14, command=self._save).pack(side="right")
        tk.Button(btns, text="取消", font=(font, 10), bg="#e8ecf7", fg=NAVY,
                  relief="solid", bd=1, padx=10,
                  command=self.window.destroy).pack(side="right", padx=6)

    def _reset(self) -> None:
        self.var_snap.set(True)
        self.var_zone.set(25)
        self.var_mirror.set(True)

    def _save(self) -> None:
        config = self.widget.config
        config.set("snapOn", bool(self.var_snap.get()))
        config.set("snapZonePct", max(5, min(50, int(self.var_zone.get()))))
        config.set("mirrorOnLeft", bool(self.var_mirror.get()))
        config.save()
        self.widget._snap()
        self.window.destroy()


class ResourceManagerWindow:
    """资源管理 — list imported images/audio and let the user remove them."""

    def __init__(self, widget) -> None:
        self.widget = widget
        font = widget.ui_font
        self.window = tk.Toplevel(widget.root)
        self.window.title("资源管理")
        self.window.configure(bg=PANEL_BG)
        self.window.geometry("560x420")
        self.window.transient(widget.root)

        frame = tk.Frame(self.window, bg=PANEL_BG, padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="资源管理", bg=PANEL_BG, fg=NAVY,
                 font=(font, 12, "bold")).pack(anchor="w")
        tk.Label(frame, text="挂件当前使用的图片与音频。删除只会移除你自己导入的文件，"
                            "随包自带的不受影响。",
                 bg=PANEL_BG, fg=MUTED, font=(font, 9), justify="left").pack(anchor="w", pady=(0, 8))

        sections = (
            ("角色图片", widget.assets / "roles", ("*.png", "*.gif")),
            ("泡泡图片", widget.assets / "bubbles", ("*.png", "*.gif")),
            ("音效片段", widget.assets / "sounds", ("*.mp3", "*.wav")),
        )
        self.lists: list[tuple[tk.Listbox, object]] = []
        for title, directory, patterns in sections:
            tk.Label(frame, text=title, bg=PANEL_BG, fg=NAVY,
                     font=(font, 10, "bold")).pack(anchor="w", pady=(6, 2))
            box = tk.Listbox(frame, height=4, font=(font, 10), bg=CARD_BG, fg=NAVY,
                             relief="solid", bd=1)
            box.pack(fill="x")
            files: list[object] = []
            if directory.is_dir():
                for pattern in patterns:
                    files.extend(sorted(directory.glob(pattern)))
            for path in files:
                box.insert("end", f"{path.name}  ({path.stat().st_size // 1024} KB)")
            self.lists.append((box, files))

        btns = tk.Frame(frame, bg=PANEL_BG)
        btns.pack(fill="x", pady=(10, 0))
        tk.Button(btns, text="删除选中", font=(font, 10), bg="#fdecea", fg="#c0392b",
                  relief="solid", bd=1, padx=10, command=self._delete).pack(side="left")
        tk.Button(btns, text="关闭", font=(font, 10), bg=NAVY, fg=WHITE, relief="flat",
                  padx=14, command=self.window.destroy).pack(side="right")
        self.status = tk.Label(frame, text="", bg=PANEL_BG, fg=MUTED, font=(font, 9))
        self.status.pack(anchor="w", pady=(6, 0))

    def _delete(self) -> None:
        removed = 0
        for box, files in self.lists:
            selection = list(box.curselection())
            for index in reversed(selection):
                if index >= len(files):
                    continue
                path = files[index]
                try:
                    path.unlink()
                    removed += 1
                    box.delete(index)
                    files.pop(index)
                except OSError as exc:
                    self.status.configure(text=f"删除失败: {exc}")
        if removed:
            self.widget.sprites.clear()
            self.widget._image_cache.clear()
            self.widget._whale_bounds = None
            self.widget._render()
            self.widget._apply_mask()
            self.status.configure(text=f"已删除 {removed} 个文件")
