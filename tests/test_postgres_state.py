import os
import sys
from types import SimpleNamespace

import pytest

from paramesh.postgres_state import PostgresStateDB
from paramesh.coordinator import Coordinator
from paramesh.rpc import training_pb2 as pb
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


@pytest.mark.skipif(
    not os.environ.get("PARAMESH_POSTGRES_DSN"), reason="PostgreSQL integration opt-in"
)
def test_postgres_coordinator_replacement_recovers_worker_session_state():
    dsn = os.environ["PARAMESH_POSTGRES_DSN"]
    config = pb.RunConfig(
        run_id="postgres-ha-test",
        mode=pb.SYNCHRONOUS,
        shard_endpoints=["127.0.0.1:1"],
        worker_ids=["worker-0"],
        learning_rate=0.05,
        barrier_timeout_seconds=5,
    )
    primary_store = PostgresStateDB(dsn, lock_name="postgres-ha-test")
    primary = Coordinator(config, state=primary_store)
    session = primary.register("worker-0", 1)
    primary.heartbeat(
        pb.HeartbeatRequest(
            run_id=config.run_id,
            worker_id="worker-0",
            session_id=session.session_id,
            step=3,
            parameter_version=3,
        )
    )
    primary_store.close()
    replacement_store = PostgresStateDB(dsn, lock_name="postgres-ha-test")
    replacement = Coordinator(config, state=replacement_store)
    assert replacement.status().global_step == 3
    replacement_session = replacement.register("worker-0", 1)
    assert replacement_session.generation == 2
    with pytest.raises(PermissionError):
        replacement.heartbeat(
            pb.HeartbeatRequest(
                run_id=config.run_id,
                worker_id="worker-0",
                session_id=session.session_id,
                step=4,
                parameter_version=4,
            )
        )
    replacement_store.close()
