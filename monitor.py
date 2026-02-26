from __future__ import annotations

from threading import Event, Lock, Thread
from typing import Any

from scraper import TikTokScrapeError, fetch_tiktok_profile
from storage import MonitorStore, utc_now_iso

NUMERIC_FIELDS = ("followers", "following", "likes", "videos_count")
TEXT_FIELDS = ("nickname", "bio")
BOOLEAN_FIELDS = ("verified",)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def detect_profile_changes(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> list[dict[str, Any]]:
    if previous is None:
        return []

    events: list[dict[str, Any]] = []

    for field in NUMERIC_FIELDS:
        old_value = _as_int(previous.get(field))
        new_value = _as_int(current.get(field))
        if old_value is None or new_value is None or old_value == new_value:
            continue
        delta = new_value - old_value
        events.append(
            {
                "metric": field,
                "old_value": old_value,
                "new_value": new_value,
                "delta": delta,
                "message": f"{field} changed from {old_value} to {new_value} ({delta:+d}).",
            }
        )

    for field in TEXT_FIELDS:
        old_value = previous.get(field)
        new_value = current.get(field)
        if old_value == new_value:
            continue
        events.append(
            {
                "metric": field,
                "old_value": old_value,
                "new_value": new_value,
                "delta": None,
                "message": f"{field} changed.",
            }
        )

    for field in BOOLEAN_FIELDS:
        old_value = bool(previous.get(field))
        new_value = bool(current.get(field))
        if old_value == new_value:
            continue
        events.append(
            {
                "metric": field,
                "old_value": old_value,
                "new_value": new_value,
                "delta": None,
                "message": f"{field} changed from {old_value} to {new_value}.",
            }
        )

    return events


class TikTokMonitorService:
    def __init__(self, store: MonitorStore, interval_seconds: int = 900) -> None:
        self.store = store
        self.interval_seconds = interval_seconds
        self._stop_event = Event()
        self._run_lock = Lock()
        self._thread: Thread | None = None
        self.last_run_started_at: str | None = None
        self.last_run_finished_at: str | None = None
        self.last_run_summary: dict[str, Any] | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "interval_seconds": self.interval_seconds,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_run_summary": self.last_run_summary,
        }

    def start(self) -> bool:
        if self.is_running:
            return False
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, name="tiktok-monitor", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if not self.is_running:
            return False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        return True

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self.interval_seconds)

    def run_once(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"status": "busy", "checked": 0, "failed": 0, "accounts": 0}

        self.last_run_started_at = utc_now_iso()
        try:
            accounts = self.store.list_watch_accounts(active_only=True)
            checked = 0
            failed = 0

            for account in accounts:
                ok = self.check_account(account["username"])
                if ok:
                    checked += 1
                else:
                    failed += 1

            summary = {
                "status": "ok",
                "accounts": len(accounts),
                "checked": checked,
                "failed": failed,
            }
            self.last_run_summary = summary
            return summary
        finally:
            self.last_run_finished_at = utc_now_iso()
            self._run_lock.release()

    def check_account(self, username: str) -> bool:
        previous = self.store.get_latest_snapshot(username)
        try:
            current = fetch_tiktok_profile(username)
        except TikTokScrapeError as exc:
            self.store.record_failure(username, str(exc))
            return False
        except Exception as exc:  # Keep monitor cycle alive while recording explicit failures.
            self.store.record_failure(username, f"{exc.__class__.__name__}: {exc}")
            return False

        self.store.save_snapshot(current)
        events = detect_profile_changes(previous, current)
        self.store.record_events(current["username"], events)
        return True
