import os
import sys
from types import SimpleNamespace

import pytest

from paramesh.postgres_state import PostgresStateDB
from paramesh.state import MAX_STATE_BYTES


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if query.startswith("SELECT pg_try_advisory_lock"):
            acquired = not self.connection.shared["locked"]
            self.connection.shared["locked"] = acquired
            self.connection.acquired = acquired
            self.row = (acquired,)
        elif query.startswith("CREATE TABLE"):
            self.row = None
        elif query.startswith("SELECT value"):
            item = self.connection.shared["values"].get(params[0])
            self.row = item
        else:
            self.connection.shared["values"][params[0]] = (params[1], params[2])

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, shared):
        self.shared = shared
        self.acquired = False

    def cursor(self):
        return _Cursor(self)

    def close(self):
        if self.acquired:
            self.shared["locked"] = False


def test_postgres_state_unit_contract(monkeypatch):
    shared = {"locked": False, "values": {}}
    fake_psycopg = SimpleNamespace(connect=lambda *_args, **_kwargs: _Connection(shared))
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    with pytest.raises(ValueError, match="DSN"):
        PostgresStateDB("")
    store = PostgresStateDB("postgresql://test")
    assert store.get("missing") is None
    store.put("x", b"payload")
    assert store.get("x") == b"payload"
    with pytest.raises(ValueError, match="size limit"):
        store.put("large", b"x" * (MAX_STATE_BYTES + 1))
    shared["values"]["large"] = (b"x" * (MAX_STATE_BYTES + 1), "")
    with pytest.raises(ValueError, match="size limit"):
        store.get("large")
    shared["values"]["x"] = (b"payload", "bad")
    with pytest.raises(ValueError, match="checksum"):
        store.get("x")
    with pytest.raises(OSError, match="already held"):
        PostgresStateDB("postgresql://test")
    store.close()


@pytest.mark.skipif(
    not os.environ.get("PARAMESH_POSTGRES_DSN"), reason="PostgreSQL integration opt-in"
)
def test_postgres_state_roundtrip_and_fencing():
    dsn = os.environ["PARAMESH_POSTGRES_DSN"]
    primary = PostgresStateDB(dsn)
    try:
        primary.put("coordinator-test", b"durable")
        assert primary.get("coordinator-test") == b"durable"
        with pytest.raises(OSError, match="already held"):
            PostgresStateDB(dsn)
    finally:
        primary.close()
    replacement = PostgresStateDB(dsn)
    try:
        assert replacement.get("coordinator-test") == b"durable"
    finally:
        replacement.close()
