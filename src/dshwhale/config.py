"""Configuration store for the DeepSeek whale widget.

Config lives in ``$XDG_CONFIG_HOME/dsh-whale/config.json`` (default
``~/.config/dsh-whale/config.json``) with ``0600`` permissions, because it holds
the DeepSeek API key.

Security note: the API key is stored base64-encoded, **not** encrypted. Any
process running as your user can read it. On Linux there is no portable
keyring-free way to hide a local secret, so this is deliberate: it keeps the
key out of casual ``grep`` output and out of the repo, and nothing more. If you
need real protection, keep the key in the ``DEEPSEEK_API_KEY`` environment
variable and leave the stored key empty.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

APP_NAME = "dsh-whale"

#: Settings defaults, mirroring the upstream widget's desktop build.
DEFAULTS: dict[str, Any] = {
    "version": 1,
    "settings": {
        "scale": 1.5,
        "bubbleOn": True,
        "refreshSec": 60,
        "showTodayUsage": True,
        "snapOn": True,
        "alwaysOnTop": True,
        "maskEnabled": True,
        #: Built-in sound set: "duck" (小黄鸭) or "fx1" (音效1); anything else
        #: uses your own assets/sounds/press.mp3 + release.mp3.
        "soundSet": "duck",
        #: Keep the widget from docking on top of a desktop panel. A transparent
        #: widget over a panel shows the panel's colour through it, which reads
        #: as a coloured block behind the whale.
        "avoidPanels": True,
    },
    "pos": {"hAnchor": "right", "vAnchor": "bottom", "x": None, "y": None},
    "secrets": {"apiKeyB64": None},
    "usage": {
        "date": None,
        "lastBalance": None,
        "todayUsage": 0.0,
        "currency": None,
        "history": {},
        "seenAt": None,
    },
    "ui": {"menuButtonHidden": False},
    #: Bubble content is owned by :mod:`dshwhale.bubbles`; it is seeded lazily
    #: with :func:`dshwhale.bubbles.default_bubbles` so the schema stays in one
    #: place. An empty dict here simply means "use the defaults".
    "bubbles": {},
}


def config_dir() -> Path:
    """Return the XDG config directory for the widget."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Load, mutate and atomically persist the widget configuration."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else config_path()
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        self.data = _deep_merge(DEFAULTS, raw)
        self._harden()

    def save(self) -> bool:
        """Write the config atomically with 0600 permissions."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".config-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.data, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            return True
        except OSError:
            return False

    def _harden(self) -> None:
        try:
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -------------------------------------------------------------- access
    @property
    def settings(self) -> dict[str, Any]:
        return self.data.setdefault("settings", {})

    @property
    def usage(self) -> dict[str, Any]:
        return self.data.setdefault("usage", {})

    @property
    def pos(self) -> dict[str, Any]:
        return self.data.setdefault("pos", {})

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value

    # ------------------------------------------------------------- secrets
    @property
    def api_key(self) -> str | None:
        """Return the effective API key: environment wins over the stored one."""
        env = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        if env:
            return env
        return self.stored_api_key

    @property
    def stored_api_key(self) -> str | None:
        blob = self.data.get("secrets", {}).get("apiKeyB64")
        if not blob:
            return None
        try:
            return base64.b64decode(blob.encode("ascii")).decode("utf-8").strip() or None
        except (ValueError, UnicodeDecodeError):
            return None

    def set_api_key(self, key: str | None) -> None:
        key = (key or "").strip()
        secrets = self.data.setdefault("secrets", {})
        if key:
            secrets["apiKeyB64"] = base64.b64encode(key.encode("utf-8")).decode("ascii")
        else:
            secrets["apiKeyB64"] = None
        self.save()

    @property
    def has_stored_key(self) -> bool:
        return bool(self.data.get("secrets", {}).get("apiKeyB64"))

    @property
    def key_from_env(self) -> bool:
        return bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip())
