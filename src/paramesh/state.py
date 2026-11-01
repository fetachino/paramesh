"""Small checksummed SQLite records, committed before acknowledging network work."""

import hashlib
import os
import sqlite3
import sys
import threading
from pathlib import Path

MAX_STATE_BYTES = 16 * 1024 * 1024


class StateDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path.with_suffix(path.suffix + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self._lease = os.fdopen(descriptor, "r+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lease.close()
            raise OSError("State store is already in use by another process") from error
        connection = None
        try:
            connection = sqlite3.connect(path, check_same_thread=False, timeout=10)
            self.connection = connection
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value BLOB NOT NULL, "
                "checksum TEXT NOT NULL)"
            )
            self.connection.commit()
        except Exception:
            if connection is not None:
                connection.close()
            self._lease.close()
            raise
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
        with self.lock:
            self.connection.close()
            self._lease.close()
