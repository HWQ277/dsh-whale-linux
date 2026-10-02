"""DeepSeek balance client (stdlib only).

Mirrors the upstream widget's behaviour:

* ``GET https://api.deepseek.com/user/balance`` with ``Authorization: Bearer``
* each wallet entry is ``{currency, total_balance, granted_balance, topped_up_balance}``
* prefer a CNY wallet with a positive balance, else any positive wallet, else CNY
* retry once on transport errors and on 5xx; fail fast on 4xx
* an 8s timeout keeps two attempts well inside the UI's own timeout
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

BALANCE_URL = "https://api.deepseek.com/user/balance"
TIMEOUT_SEC = 8.0
USER_AGENT = "dsh-whale-linux/1.0 (+https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)"


@dataclass
class Balance:
    """A successful balance reading."""

    total: float
    currency: str
    granted: float | None = None
    topped_up: float | None = None
    at: str = ""

    def __post_init__(self) -> None:
        if not self.at:
            self.at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def fmt(self) -> str:
        """Format the way the upstream widget does."""
        text = f"{self.total:,.2f}"
        if self.currency == "CNY":
            return f"¥ {text}"
        return f"{text} {self.currency}"


@dataclass
class BalanceError:
    """A failed balance attempt."""

    code: str  # NO_KEY | HTTP | PARSE | SHAPE | NET
    message: str
    transient: bool = False
    status: int | None = None


def _to_float(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def pick_wallet(infos: object) -> dict | None:
    """Choose the wallet to report, following the upstream preference order."""
    if not isinstance(infos, list) or not infos:
        return None

    def amount(entry: object) -> float | None:
        if not isinstance(entry, dict):
            return None
        return _to_float(entry.get("total_balance"))

    def is_cny(entry: object) -> bool:
        return isinstance(entry, dict) and entry.get("currency") == "CNY"

    for entry in infos:
        amt = amount(entry)
        if is_cny(entry) and amt is not None and amt > 0:
            return entry  # type: ignore[return-value]
    for entry in infos:
        amt = amount(entry)
        if amt is not None and amt > 0:
            return entry  # type: ignore[return-value]
    for entry in infos:
        if is_cny(entry):
            return entry  # type: ignore[return-value]
    entry = infos[0]
    return entry if isinstance(entry, dict) else None


def fetch_balance(api_key: str | None, *, timeout: float = TIMEOUT_SEC) -> Balance | BalanceError:
    """Fetch the account balance. Never raises; returns a result object."""
    key = (api_key or "").strip()
    if not key:
        return BalanceError(
            "NO_KEY",
            "未配置 API Key · 右键鲸鱼 → 设置",
        )

    last_error: Exception | None = None
    last_status: int | None = None

    for attempt in range(2):
        request = urllib.request.Request(
            BALANCE_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(65536)
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            last_error = exc
            # 4xx is the caller's fault (bad key) — no point retrying.
            if exc.code < 500:
                break
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            continue

        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return BalanceError("PARSE", "余额接口返回不是合法 JSON")

        wallet = pick_wallet(payload.get("balance_infos") if isinstance(payload, dict) else None)
        if wallet is None:
            return BalanceError("SHAPE", "余额接口返回结构异常")

        total = _to_float(wallet.get("total_balance"))
        if total is None:
            return BalanceError("SHAPE", "余额接口缺少 total_balance")

        return Balance(
            total=total,
            currency=str(wallet.get("currency") or "CNY"),
            granted=_to_float(wallet.get("granted_balance")),
            topped_up=_to_float(wallet.get("topped_up_balance")),
        )

    if last_status == 401:
        return BalanceError("HTTP", "API Key 无效 (401)", status=401)
    if last_status == 403:
        return BalanceError("HTTP", "API Key 无权限 (403)", status=403)
    if last_status is not None:
        return BalanceError("HTTP", f"余额接口 HTTP {last_status}", status=last_status)

    reason = str(last_error) if last_error else "未知网络错误"
    return BalanceError("NET", f"网络请求失败: {reason[:90]}", transient=True)
