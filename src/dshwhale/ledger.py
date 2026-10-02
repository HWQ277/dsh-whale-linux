"""Today's-spend accounting from balance observations.

The upstream widget derives "today's spend" without any token or usage API: it
polls the balance and treats a *decrease* as spend. An *increase* means a top-up
or a granted credit, which is recorded separately so it never cancels out spend
that already happened. That is exactly what this module does.

All day boundaries and the peak/off-peak schedule use **Beijing time (UTC+8)**,
matching the upstream pricing calendar (peak = workdays 09:00-12:00 and
14:00-18:00; weekends are entirely off-peak).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

BEIJING = timezone(timedelta(hours=8))

#: Beijing-time peak windows (start_hour inclusive, end_hour exclusive).
PEAK_WINDOWS = ((9, 12), (14, 18))

HISTORY_LIMIT_DAYS = 90


def beijing_now() -> datetime:
    return datetime.now(BEIJING)


def beijing_day(moment: datetime | None = None) -> str:
    """Return the Beijing calendar day as ``YYYY-MM-DD``."""
    moment = moment or beijing_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BEIJING)
    return moment.astimezone(BEIJING).strftime("%Y-%m-%d")


def is_peak(moment: datetime | None = None) -> bool:
    """True during Beijing-time peak pricing windows (weekends are off-peak)."""
    moment = moment or beijing_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BEIJING)
    local = moment.astimezone(BEIJING)
    if local.weekday() >= 5:  # Saturday (5) / Sunday (6)
        return False
    return any(start <= local.hour < end for start, end in PEAK_WINDOWS)


def next_transition(moment: datetime | None = None) -> tuple[str, datetime]:
    """Return ``(label, when)`` for the next peak/off-peak boundary."""
    moment = moment or beijing_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BEIJING)
    local = moment.astimezone(BEIJING)
    # Search forward minute-by-minute is wasteful; step over the known windows.
    for day_offset in range(0, 8):
        day = (local + timedelta(days=day_offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if day.weekday() >= 5:
            continue
        for start, end in PEAK_WINDOWS:
            for hour in (start, end):
                candidate = day.replace(hour=hour)
                if candidate > local:
                    label = "高峰" if hour == start else "空闲"
                    return label, candidate
    return "空闲", local + timedelta(hours=1)


def peak_label(moment: datetime | None = None) -> str:
    return "高峰时段" if is_peak(moment) else "空闲时段"


class Ledger:
    """Tracks observed balance deltas across days.

    ``update`` is called with each fresh balance reading. It returns a small
    summary describing what changed, so the UI can react (roll the number, show
    a "balance adjusted" hint, and so on).
    """

    def __init__(self, usage: dict[str, Any]) -> None:
        self.usage = usage
        self._roll_day()

    # ------------------------------------------------------------- helpers
    def _roll_day(self) -> None:
        today = beijing_day()
        if self.usage.get("date") != today:
            previous = self.usage.get("date")
            last = self.usage.get("lastBalance")
            if previous and last is not None:
                history = self.usage.setdefault("history", {})
                history[previous] = round(float(last), 8)
                self._trim_history()
            self.usage["date"] = today
            self.usage["todayUsage"] = 0.0
            self.usage["lastBalance"] = None
        self.usage.setdefault("history", {})
        self.usage.setdefault("todayUsage", 0.0)

    def _trim_history(self) -> None:
        history = self.usage.get("history") or {}
        if len(history) <= HISTORY_LIMIT_DAYS:
            return
        for key in sorted(history)[:-HISTORY_LIMIT_DAYS]:
            history.pop(key, None)

    # -------------------------------------------------------------- public
    @property
    def today_usage(self) -> float:
        return float(self.usage.get("todayUsage") or 0.0)

    @property
    def currency(self) -> str | None:
        return self.usage.get("currency")

    def last_balance(self) -> float | None:
        value = self.usage.get("lastBalance")
        return float(value) if value is not None else None

    def update(self, total: float, currency: str) -> dict[str, Any]:
        """Record a fresh reading; returns ``{spent, topped_up, changed}``."""
        self._roll_day()
        previous = self.usage.get("lastBalance")
        self.usage["currency"] = currency
        self.usage["seenAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        result = {"spent": 0.0, "topped_up": 0.0, "changed": False}
        if previous is not None:
            delta = float(previous) - float(total)
            if delta > 1e-9:
                # Balance went down: that is observed spend.
                self.usage["todayUsage"] = round(self.today_usage + delta, 8)
                result["spent"] = delta
                result["changed"] = True
            elif delta < -1e-9:
                # Balance went up: a top-up or granted credit. Record it but do
                # NOT subtract it from today's spend.
                self.usage["lastTopUp"] = round(-delta, 8)
                self.usage["lastTopUpAt"] = beijing_now().strftime("%Y-%m-%d %H:%M")
                result["topped_up"] = -delta

        self.usage["lastBalance"] = round(float(total), 8)
        return result

    def reset_today(self) -> None:
        self.usage["todayUsage"] = 0.0

    def history_series(self, days: int = 7) -> list[tuple[str, float]]:
        """Return the last ``days`` days of recorded closing balances."""
        history = self.usage.get("history") or {}
        today = beijing_day()
        out: list[tuple[str, float]] = []
        for offset in range(days - 1, -1, -1):
            day = (beijing_now() - timedelta(days=offset)).strftime("%Y-%m-%d")
            if day == today:
                continue
            if day in history:
                out.append((day, float(history[day])))
        return out
