"""Optional PostgreSQL-backed coordinator state and fencing lease."""

import hashlib
from typing import Any

from paramesh.state import MAX_STATE_BYTES


class PostgresStateDB:
    """Checksummed state with a session-scoped PostgreSQL advisory lock.

    The lock makes a second coordinator fail closed while the first session is alive;
    closing the connection releases it so a replacement can recover durable state.
    """

    def __init__(self, dsn: str, *, lock_name: str = "paramesh-coordinator") -> None:
        if not dsn or not lock_name:
            raise ValueError("A PostgreSQL DSN and lock name are required")
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - exercised by optional install
            raise RuntimeError(
                "Install the 'ha' extra to use PostgreSQL coordinator state"
            ) from error
        try:
            self.connection: Any = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (lock_name,))
                row = cursor.fetchone()
                if row is None or not row[0]:
                    raise OSError("Coordinator lease is already held")
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS paramesh_state ("
                    "key TEXT PRIMARY KEY, value BYTEA NOT NULL, checksum TEXT NOT NULL)"
                )
        except Exception:
            if "connection" in self.__dict__:
                self.connection.close()
            raise

    def get(self, key: str) -> bytes | None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT value, checksum FROM paramesh_state WHERE key=%s", (key,))
            row = cursor.fetchone()
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
        checksum = hashlib.sha256(payload).hexdigest()
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO paramesh_state(key, value, checksum) VALUES(%s, %s, %s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, checksum=excluded.checksum",
                (key, payload, checksum),
            )

    def close(self) -> None:
        self.connection.close()
