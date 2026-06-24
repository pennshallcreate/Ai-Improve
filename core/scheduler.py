"""Authorized-window logic + the APScheduler driver.

Governance rule: the loop may only act inside user-authorized time windows. This
module answers "are we authorized right now?" and runs a lightweight background tick
that nudges the loop to run (when auto-run is on) or go idle as windows open/close.
Window evaluation uses local wall-clock time, which is what users reason about.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler


def _parse_hhmm(value: str) -> int:
    """'HH:MM' → minutes since midnight. '24:00' is accepted as end-of-day (1440)."""
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def _window_active(window: dict, now: datetime) -> bool:
    start = _parse_hhmm(window.get("start", "00:00"))
    end = _parse_hhmm(window.get("end", "24:00"))
    minutes = now.hour * 60 + now.minute

    if window.get("type") == "once":
        if now.strftime("%Y-%m-%d") != window.get("date"):
            return False
    else:  # weekly
        if now.weekday() not in window.get("days", []):
            return False

    if end <= start:  # tolerate inverted ranges by treating as same-day span
        end = start
    return start <= minutes < end


def is_authorized(windows: list[dict], now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return any(_window_active(w, now) for w in windows)


def current_window(windows: list[dict], now: Optional[datetime] = None) -> Optional[dict]:
    now = now or datetime.now()
    for w in windows:
        if _window_active(w, now):
            return w
    return None


def next_window_start(windows: list[dict], now: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort time the next authorized window opens (for UI countdowns)."""
    now = now or datetime.now()
    best: Optional[datetime] = None
    for day_offset in range(0, 8):
        day = now + timedelta(days=day_offset)
        for w in windows:
            try:
                start = _parse_hhmm(w.get("start", "00:00"))
            except (ValueError, AttributeError):
                continue
            candidate = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=start)
            if candidate <= now:
                continue
            if w.get("type") == "once":
                if candidate.strftime("%Y-%m-%d") != w.get("date"):
                    continue
            elif candidate.weekday() not in w.get("days", []):
                continue
            if best is None or candidate < best:
                best = candidate
    return best


def authorize_now_window(minutes: int = 60, now: Optional[datetime] = None) -> dict:
    """Build a one-off window starting now — used by the UI's 'authorize now' button.

    This is genuine user authorization (the user clicks it), so it satisfies the
    governance constraint while letting the loop be demoed outside the usual schedule.
    """
    now = now or datetime.now()
    end = now + timedelta(minutes=minutes)
    end_minutes = end.hour * 60 + end.minute
    # Clamp to the same day so the window can't silently wrap past midnight.
    if end.strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
        end_minutes = 24 * 60
    return {
        "type": "once",
        "date": now.strftime("%Y-%m-%d"),
        "start": f"{now.hour:02d}:{now.minute:02d}",
        "end": f"{end_minutes // 60:02d}:{end_minutes % 60:02d}",
    }


class Ticker:
    """Drives the loop on an interval via APScheduler's background thread."""

    def __init__(self, tick_seconds: int, on_tick):
        self._scheduler = BackgroundScheduler(daemon=True)
        self._tick_seconds = max(5, int(tick_seconds))
        self._on_tick = on_tick
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._scheduler.add_job(
            self._safe_tick,
            "interval",
            seconds=self._tick_seconds,
            id="loop_tick",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self._started = True

    def _safe_tick(self) -> None:
        try:
            self._on_tick()
        except Exception:  # noqa: BLE001 - a tick must never kill the scheduler thread
            pass

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
