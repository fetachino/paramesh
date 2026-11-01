"""Small checksummed SQLite records, committed before acknowledging network work."""

import hashlib
import sqlite3
import threading
from pathlib import Path

MAX_STATE_BYTES = 16 * 1024 * 1024


class StateDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value BLOB NOT NULL, "
            "checksum TEXT NOT NULL)"
        )
        self.connection.commit()
        self.lock = threading.Lock()

    def get(self, key: str) -> bytes | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT value, checksum FROM state WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        payload = bytes(row[0])
        if len(payload) > MAX_STATE_BYTES:
            raise ValueError("Durable state exceeds size limit")
        if hashlib.sha256(payload).hexdigest() != row[1]:
            raise ValueError("Durable state checksum mismatch")
        return payload

    def put(self, key: str, payload: bytes) -> None:
        if len(payload) > MAX_STATE_BYTES:
            raise ValueError("Durable state exceeds size limit")
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO state(key, value, checksum) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, checksum=excluded.checksum",
                (key, payload, hashlib.sha256(payload).hexdigest()),
            )

    def close(self) -> None:
        self.connection.close()
