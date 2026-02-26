from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MonitorStore:
    def __init__(self, db_path: str | Path = "iris.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        self._ensure_schema(connection)
        return connection

    def _initialize(self) -> None:
        # Force a first successful schema setup at startup.
        with self._connect():
            pass

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watch_accounts (
                username TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                last_checked_at TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                nickname TEXT,
                bio TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                followers INTEGER,
                following INTEGER,
                likes INTEGER,
                videos_count INTEGER,
                profile_url TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_username_checked
                ON snapshots (username, checked_at DESC);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                metric TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                delta INTEGER,
                message TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_detected
                ON events (detected_at DESC);

            CREATE TABLE IF NOT EXISTS failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                error TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_failures_checked
                ON failures (checked_at DESC);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    def add_watch_account(self, username: str) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watch_accounts (username, created_at, active)
                VALUES (?, ?, 1)
                ON CONFLICT(username) DO UPDATE SET active = 1
                """,
                (username, now),
            )

    def deactivate_watch_account(self, username: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE watch_accounts SET active = 0 WHERE username = ?",
                (username,),
            )
        return cursor.rowcount > 0

    def list_watch_accounts(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = """
            SELECT username, created_at, active, last_checked_at, last_error
            FROM watch_accounts
        """
        params: tuple[Any, ...] = ()
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY username COLLATE NOCASE ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_watch_accounts_with_latest(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.username,
                    w.created_at,
                    w.active,
                    w.last_checked_at,
                    w.last_error,
                    s.checked_at AS snapshot_checked_at,
                    s.nickname,
                    s.followers,
                    s.following,
                    s.likes,
                    s.videos_count
                FROM watch_accounts w
                LEFT JOIN snapshots s
                    ON s.id = (
                        SELECT id
                        FROM snapshots
                        WHERE username = w.username
                        ORDER BY id DESC
                        LIMIT 1
                    )
                WHERE w.active = 1
                ORDER BY w.username COLLATE NOCASE ASC
                """
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_latest_snapshot(self, username: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT username, checked_at, nickname, bio, verified, followers, following, likes, videos_count, profile_url
                FROM snapshots
                WHERE username = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (username,),
            ).fetchone()
        return _row_to_dict(row) if row else None

    def save_snapshot(self, profile: dict[str, Any]) -> None:
        username = str(profile["username"])
        checked_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watch_accounts (username, created_at, active)
                VALUES (?, ?, 1)
                ON CONFLICT(username) DO NOTHING
                """,
                (username, checked_at),
            )
            conn.execute(
                """
                INSERT INTO snapshots (
                    username, checked_at, nickname, bio, verified,
                    followers, following, likes, videos_count, profile_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    checked_at,
                    profile.get("nickname"),
                    profile.get("bio"),
                    1 if profile.get("verified") else 0,
                    _to_int(profile.get("followers")),
                    _to_int(profile.get("following")),
                    _to_int(profile.get("likes")),
                    _to_int(profile.get("videos_count")),
                    profile.get("profile_url") or f"https://www.tiktok.com/@{username}",
                ),
            )
            conn.execute(
                """
                UPDATE watch_accounts
                SET last_checked_at = ?, last_error = NULL
                WHERE username = ?
                """,
                (checked_at, username),
            )

    def record_events(self, username: str, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        detected_at = utc_now_iso()
        values = [
            (
                username,
                detected_at,
                event["metric"],
                None if event.get("old_value") is None else str(event.get("old_value")),
                None if event.get("new_value") is None else str(event.get("new_value")),
                _to_int(event.get("delta")),
                event["message"],
            )
            for event in events
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO events (
                    username, detected_at, metric, old_value, new_value, delta, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

    def record_failure(self, username: str, error: str) -> None:
        checked_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watch_accounts (username, created_at, active)
                VALUES (?, ?, 1)
                ON CONFLICT(username) DO NOTHING
                """,
                (username, checked_at),
            )
            conn.execute(
                "INSERT INTO failures (username, checked_at, error) VALUES (?, ?, ?)",
                (username, checked_at, error),
            )
            conn.execute(
                """
                UPDATE watch_accounts
                SET last_checked_at = ?, last_error = ?
                WHERE username = ?
                """,
                (checked_at, error, username),
            )

    def get_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, detected_at, metric, old_value, new_value, delta, message
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_recent_failures(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, checked_at, error
                FROM failures
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_snapshots(self, username: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, username, checked_at, nickname, bio, verified, followers, following, likes, videos_count, profile_url
                FROM snapshots
                WHERE username = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (username, limit),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_setting(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def get_all_settings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings ORDER BY key ASC"
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def clear_monitor_data(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                DELETE FROM events;
                DELETE FROM failures;
                DELETE FROM snapshots;
                DELETE FROM watch_accounts;
                """
            )
