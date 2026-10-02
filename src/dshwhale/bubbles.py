"""Speech-bubble content: click sequences, modules, styling and animations.

The upstream widget's signature feature is that the bubble is not a fixed
message — it is a small document. Each bubble is a list of *lines*, each line is
a list of *modules*, and modules are typed (plain text, balance, today's spend,
peak/off-peak status, a random pick from weighted alternatives, or an image).
Every module carries its own colour / font / size / weight, and the bubble
temporarily floats out, then fades.

This module is pure data + geometry: no Tk, no I/O. ``widget.py`` renders what
this produces.
"""

from __future__ import annotations

import base64
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from .config import Config
from .theme import BUBBLE_TEXT as NAVY_TEXT

# --- module kinds -----------------------------------------------------------
TEXT = "text"
BALANCE = "balance"
TODAY = "today"
PEAK = "peak"
RANDOM = "random"
IMAGE = "image"

MODULE_KINDS = (TEXT, BALANCE, TODAY, PEAK, RANDOM, IMAGE)

#: Peak/off-peak presentation styles, mirroring the upstream options.
PEAK_STYLES = ("default", "liangwen", "qiangqiang", "terse")

#: Placeholders usable inside any text module.
PLACEHOLDERS = ("{balance}", "{today}", "{peak}", "{currency}", "{name}")

# ---------------------------------------------------------------------------
# Module sizes
# ---------------------------------------------------------------------------
# ``Module.size`` is a level in 1..50, exactly like the upstream editor. Upstream
# turns a level into a CSS unit multiple with::
#
#     function bubbleModuleFontU(level) {
#       var n = Math.max(1, Math.min(50, Math.round(Number(level) || 6)))
#       return Math.round(40 + (n - 1) * 200 / 49)     // 1 -> 40 ... 50 -> 240
#     }
#
# and then renders ``font-size: calc(var(--dshw-u) * that)`` where
# ``--dshw-u = base / 1026``. So level 6 -> 60u -> ~16px at the default size.
#
# The static classes (.dshwv-label 66u, .dshwv-amount 128u, .dshwv-period 104u,
# .dshwv-hint 56u) are the non-module bubble; they correspond to levels ~7, ~22,
# ~16 and ~5.
SIZE_MIN, SIZE_MAX, SIZE_DEFAULT = 1, 50, 6

#: Levels the palette uses for each built-in module type (upstream defaults).
#: Levels used by the frozen upstream default bubble (BUBBLE_DEFAULT_ITEMS[0]).
#: These are the module ``size`` values verbatim from the source.
LEVEL_TEXT = 8        # "DeepSeek 余额"  -> 69u -> ~19px
LEVEL_BALANCE = 20    # "{balance_ds}"    -> 118u -> ~32px
LEVEL_TODAY = 4       # "今日已用 {expense_ds}" -> 52u -> ~14px
LEVEL_PEAK = 2        # "{status}"        -> 44u -> ~12px
LEVEL_NEXTPEAK = 4    # "{countdown}"     -> 52u -> ~14px
LEVEL_SESSION = 4
LEVEL_LINK = 6

#: "indigo" in the upstream palette is a gradient; this is its mid tone
#: (rgb(74,102,180)) so the balance reads as the upstream 靛蓝夜曲 colour.
INDIGO = "#4A66B4"


def font_units(level: int) -> int:
    """Upstream ``bubbleModuleFontU``: level 1..50 -> CSS unit multiple."""
    n = max(SIZE_MIN, min(SIZE_MAX, int(round(level or SIZE_DEFAULT))))
    return int(round(40 + (n - 1) * 200 / 49))

#: Rendered as this when a numeric value is not available yet.
PENDING = "…"

MAX_LINES = 6
MAX_MODULES_PER_LINE = 6


@dataclass
class Module:
    """One styled fragment inside a bubble line."""

    kind: str = TEXT
    text: str = ""
    #: For RANDOM / IMAGE: ``[(value, weight), ...]``.
    choices: list[tuple[str, float]] = field(default_factory=list)
    #: IMAGE only: asset file name inside the assets directory.
    image: str = ""
    size: int = 0        # relative font size, 0 = inherit the line default
    bold: bool = False
    italic: bool = False
    underline: bool = False
    colour: str | None = None
    background: str | None = None

    # ---------------------------------------------------------------- parsing
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Module":
        kind = str(raw.get("kind") or TEXT)
        if kind not in MODULE_KINDS:
            kind = TEXT
        choices: list[tuple[str, float]] = []
        for entry in raw.get("choices") or []:
            if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                try:
                    weight = float(entry[1]) if len(entry) > 1 else 1.0
                except (TypeError, ValueError):
                    weight = 1.0
                choices.append((str(entry[0]), max(0.0, weight)))
            elif isinstance(entry, str):
                choices.append((entry, 1.0))
        return cls(
            kind=kind,
            text=str(raw.get("text") or ""),
            choices=choices,
            image=str(raw.get("image") or ""),
            size=int(raw.get("size") or 0),
            bold=bool(raw.get("bold")),
            italic=bool(raw.get("italic")),
            underline=bool(raw.get("underline")),
            colour=raw.get("colour") or None,
            background=raw.get("background") or None,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.text:
            out["text"] = self.text
        if self.choices:
            out["choices"] = [[value, weight] for value, weight in self.choices]
        if self.image:
            out["image"] = self.image
        if self.size:
            out["size"] = self.size
        for flag in ("bold", "italic", "underline"):
            if getattr(self, flag):
                out[flag] = True
        if self.colour:
            out["colour"] = self.colour
        if self.background:
            out["background"] = self.background
        return out


@dataclass
class Bubble:
    """One bubble: an ordered list of lines, each holding up to six modules."""

    lines: list[list[Module]] = field(default_factory=list)
    #: Auto-close delay in seconds; 0 means "stay until dismissed". Matches the
    #: upstream default of 5 seconds (upstream BUBBLE_MS / CHANGE_MS timings).
    close_after: int = 5

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Bubble":
        lines: list[list[Module]] = []
        for line in (raw.get("lines") or [])[:MAX_LINES]:
            modules = [Module.from_dict(m) for m in (line or [])[:MAX_MODULES_PER_LINE]]
            if modules:
                lines.append(modules)
        try:
            close_after = int(raw.get("closeAfter", 5))
        except (TypeError, ValueError):
            close_after = 5
        return cls(lines=lines, close_after=max(0, min(600, close_after)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines": [[m.to_dict() for m in line] for line in self.lines],
            "closeAfter": self.close_after,
        }


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
def _line(*modules: Module) -> list[Module]:
    return list(modules)


def default_bubbles() -> dict[str, Any]:
    """The factory bubble set, copied from upstream ``BUBBLE_DEFAULT_ITEMS``.

    Upstream freezes two items:

    * item 0 — the 靛蓝余额卡: ``DeepSeek 余额`` (level 8) / ``{balance_ds}``
      (level 20) / ``今日已用 {expense_ds}`` (level 4) / ``{status}`` (level 2) /
      ``{countdown}`` (level 4).
    * item 1 — a weighted choice between the random-sentence bubble (weight 10)
      and an image bubble (weight 1).

    At the default 280px box those levels render as roughly 19 / 32 / 14 / 12 px.
    """
    balance_bubble = Bubble(lines=[
        _line(Module(kind=TEXT, text="DeepSeek 余额", colour=NAVY_TEXT,
                     size=LEVEL_TEXT, bold=True)),
        _line(Module(kind=BALANCE, text="{balance_ds}", colour=INDIGO,
                     size=LEVEL_BALANCE)),
        _line(Module(kind=TODAY, text="今日已用 {expense_ds}", colour="#9fb0d9",
                     size=LEVEL_TODAY),
              Module(kind=PEAK, text="{status}", colour="#ffffff",
                     size=LEVEL_PEAK, bold=True)),
        _line(Module(kind=PEAK, text="{countdown}", colour="#e0433f",
                     size=LEVEL_NEXTPEAK, bold=True)),
    ])
    random_bubble = Bubble(lines=[
        _line(Module(kind=RANDOM, colour=INDIGO, size=LEVEL_TEXT, bold=True, choices=[
            ("好模型...↓", 10.0),
            ("好女孩...↓", 10.0),
            ("哦鲸鲸...", 10.0),
            ("你好呀，我是小鲸鱼～", 4.0),
            ("点我看看 DeepSeek 余额吧", 4.0),
            ("今天也在帮你盯着钱包哦", 3.0),
            ("摸鱼可以，别忘了余额喵", 2.0),
        ])),
    ])
    return {
        "first": balance_bubble.to_dict(),
        "queue": [random_bubble.to_dict()],
        "idle": [random_bubble.to_dict()],
        "idleOn": False,
        "idleSeconds": 300,
        "advanceOnTap": True,
        "on": True,
    }


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
class BubbleRenderer:
    """Resolves modules into drawable text runs using live widget values."""

    def __init__(self, config: Config, fonts: Any) -> None:
        self.config = config
        self.fonts = fonts
        self._last_random: dict[int, str] = {}

    # ------------------------------------------------------------- accessors
    @property
    def data(self) -> dict[str, Any]:
        """Bubble settings, seeded (and persisted) with the defaults.

        ``setdefault`` alone left ``bubbles: {}`` on disk for configs created
        before this feature existed, which made every lookup return ``None`` and
        the widget showed no bubble at all.
        """
        bubbles = self.config.data.get("bubbles")
        if not isinstance(bubbles, dict) or not bubbles:
            bubbles = default_bubbles()
            self.config.data["bubbles"] = bubbles
            self.config.save()
        else:
            # Backfill keys added in later versions.
            for key, value in default_bubbles().items():
                bubbles.setdefault(key, value)
        return bubbles

    def bubble(self, key: str) -> Bubble | None:
        raw = self.data.get(key)
        if isinstance(raw, dict):
            return Bubble.from_dict(raw)
        return None

    def queue(self) -> list[Bubble]:
        out: list[Bubble] = []
        for raw in self.data.get("queue") or []:
            if isinstance(raw, dict):
                out.append(Bubble.from_dict(raw))
        return out

    # -------------------------------------------------------------- resolving
    @staticmethod
    def _pick(module: Module, index: int, memory: dict[int, str]) -> str:
        """Choose from weighted alternatives, avoiding an immediate repeat."""
        choices = [(value, weight) for value, weight in module.choices if weight > 0]
        if not choices:
            return ""
        if len(choices) == 1:
            return choices[0][0]
        previous = memory.get(index)
        pool = [c for c in choices if c[0] != previous] or choices
        total = sum(weight for _value, weight in pool)
        if total <= 0:
            return random.choice(pool)[0]
        roll = random.uniform(0, total)
        upto = 0.0
        for value, weight in pool:
            upto += weight
            if roll <= upto:
                memory[index] = value
                return value
        value = pool[-1][0]
        memory[index] = value
        return value

    def _peak_text(self, style: str) -> str:
        """Present the peak/off-peak state in one of the upstream styles."""
        from .ledger import peak_label

        peak = peak_label()
        if style == "liangwen":
            return "梁文峰谷" if peak == "高峰时段" else "梁文低谷"
        if style == "qiangqiang":
            return "!!强强!! 高峰" if peak == "高峰时段" else "~~ 空闲 ~~"
        if style == "terse":
            return "峰" if peak == "高峰时段" else "谷"
        return peak

    def resolve_line(
        self,
        line: Iterable[Module],
        values: dict[str, str],
        *,
        memory: dict[int, str] | None = None,
        cache: dict[tuple[int, int], str] | None = None,
        line_index: int = 0,
    ) -> list[tuple[str, Module]]:
        """Turn a line of modules into ``[(text, module), ...]`` runs.

        ``cache`` holds the chosen text for this display keyed by
        ``(line_index, module_index)``. The widget passes it so a random module
        keeps ONE sentence for the whole time the bubble is on screen: without
        it, every redraw re-rolled the dice (and because ``_pick`` avoids
        repeating itself, successive frames visibly cycled through the pool).
        """
        memory = memory if memory is not None else self._last_random
        runs: list[tuple[str, Module]] = []
        for index, module in enumerate(line):
            if module.kind == IMAGE:
                continue  # images are drawn separately, not as text runs
            # Value modules render their TEMPLATE (upstream stores e.g.
            # tpl='今日已用 {expense_ds}'), falling back to the bare value when
            # no template was set. Substitution happens once, below.
            if module.kind == RANDOM:
                key = (line_index, index)
                if cache is not None and key in cache:
                    text = cache[key]
                else:
                    text = self._pick(module, index, memory)
                    if cache is not None:
                        cache[key] = text
            elif module.kind == BALANCE:
                text = module.text or "{balance_ds}"
            elif module.kind == TODAY:
                text = module.text or "{expense_ds}"
            elif module.kind == PEAK:
                text = module.text or "{status}"
            else:
                text = module.text
            if module.kind == PEAK and str(self.data.get("peakStyle") or "") == "count":
                text = "{countdown}"
            if not text:
                continue
            runs.append((self.substitute(text, values), module))
        return runs

    @staticmethod
    def substitute(text: str, values: dict[str, str]) -> str:
        """Replace ``{balance}``-style placeholders."""
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        return text

    def image_modules(self, bubble: Bubble) -> list[str]:
        """Asset names for every image module in the bubble (one line each)."""
        out: list[str] = []
        for line in bubble.lines:
            for module in line:
                if module.kind == IMAGE and module.image:
                    out.append(module.image)
        return out

    def has_image(self, bubble: Bubble) -> bool:
        return bool(self.image_modules(bubble))
