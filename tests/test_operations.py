import json
import time

import pytest

from paramesh.operations import EventLog, Sessions
from paramesh.state import StateDB


def event(**changes):
    return {
        "schema_version": 1,
        "event_id": "a" * 32,
        "event": "worker_joined",
        "timestamp": time.time(),
        "service": "coordinator",
        "entry_point": "cli",
        "run_id": "test-run",
        "worker_id": "worker-0",
        "generation": 1,
        **changes,
    }


def test_events_are_validated_deduplicated_and_retained_across_restart(tmp_path):
    database = StateDB(tmp_path / "dashboard.sqlite")
    log = EventLog(database)
    record = event()
    assert log.ingest(json.dumps(record).encode())
    assert not log.ingest(json.dumps(record).encode())
    assert log.snapshot() == [record]
    database.close()
    reopened = StateDB(tmp_path / "dashboard.sqlite")
    try:
        assert EventLog(reopened).snapshot() == [record]
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"authorization": "must-not-store"},
        {"tensors": []},
        {"run_id": "<script>"},
        {"timestamp": float("nan")},
        {"event": "send_gradients"},
        {"event_id": "invalid"},
        {"generation": -1},
    ],
)
def test_untrusted_event_payloads_do_not_enter_operator_state(tmp_path, changes):
    database = StateDB(tmp_path / "dashboard.sqlite")
    try:
        log = EventLog(database)
        with pytest.raises(ValueError):
            log.ingest(json.dumps(event(**changes)).encode())
        assert log.snapshot() == []
    finally:
        database.close()


def test_sessions_require_strong_credentials_and_reject_expiry_or_tampering():
    with pytest.raises(ValueError):
        Sessions("weak")
    clock = [1000.0]
    sessions = Sessions("secret_" * 8, clock=lambda: clock[0])
    assert sessions.login("operator", "wrong") is None
    assert sessions.login("other", "secret_" * 8) is None
    assert sessions.login("operator", "non-ascii-☃") is None
    token = sessions.login("operator", "secret_" * 8)
    assert sessions.valid(token)
    assert not sessions.valid(token[:-1] + ("a" if token[-1] != "a" else "b"))
    assert not Sessions("secret_" * 8).valid(token)
    clock[0] += 8 * 3600 + 1
    assert not sessions.valid(token)
    assert not sessions.valid("malformed")


def test_checkpoint_events_require_publication_fields_and_snapshot_is_detached(tmp_path):
    database = StateDB(tmp_path / "dashboard.sqlite")
    log = EventLog(database)
    record = event(
        event="checkpoint_completed",
        checkpoint_id="verified",
        step=20,
        shard_versions=[20, 20],
        duration_seconds=0.25,
    )
    try:
        for key in ("checkpoint_id", "step", "shard_versions", "duration_seconds"):
            incomplete = {name: value for name, value in record.items() if name != key}
            with pytest.raises(ValueError):
                log.ingest(json.dumps(incomplete).encode())
        assert log.snapshot() == []
        assert log.ingest(json.dumps(record).encode())
        snapshot = log.snapshot()
        snapshot[0]["shard_versions"].clear()
        assert log.snapshot()[0]["shard_versions"] == [20, 20]
    finally:
        database.close()
