"""SQLite: welche Nachrichten schon bearbeitet wurden (kein Issue doppelt) und Sendebegrenzung."""
from __future__ import annotations

import sqlite3
import time
from typing import Optional


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS handled (
                event_id TEXT PRIMARY KEY,
                ts       REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issues (
                event_id TEXT PRIMARY KEY,
                sender   TEXT NOT NULL,
                room_id  TEXT NOT NULL,
                repo     TEXT NOT NULL,
                number   INTEGER NOT NULL,
                url      TEXT NOT NULL,
                ts       REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS issues_sender_ts ON issues(sender, ts);
            """
        )
        self.db.commit()

    def claim(self, event_id: str, now: Optional[float] = None) -> bool:
        """True genau einmal pro event_id (auch ueber Neustarts hinweg)."""
        try:
            self.db.execute("INSERT INTO handled(event_id, ts) VALUES (?, ?)",
                            (event_id, now or time.time()))
            self.db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def record_issue(self, event_id: str, sender: str, room_id: str, repo: str,
                     number: int, url: str, now: Optional[float] = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO issues VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, sender, room_id, repo, number, url, now or time.time()))
        self.db.commit()

    def recent_count(self, sender: str, seconds: int, now: Optional[float] = None) -> int:
        since = (now or time.time()) - seconds
        row = self.db.execute("SELECT COUNT(*) FROM issues WHERE sender = ? AND ts >= ?",
                              (sender, since)).fetchone()
        return int(row[0])

    def oldest_in_window(self, sender: str, seconds: int, now: Optional[float] = None) -> Optional[float]:
        since = (now or time.time()) - seconds
        row = self.db.execute("SELECT MIN(ts) FROM issues WHERE sender = ? AND ts >= ?",
                              (sender, since)).fetchone()
        return row[0]

    def prune(self, keep_seconds: int = 30 * 86400) -> None:
        self.db.execute("DELETE FROM handled WHERE ts < ?", (time.time() - keep_seconds,))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
