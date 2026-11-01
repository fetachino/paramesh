from pathlib import Path

import pytest

from paramesh.state import StateDB


def test_state_survives_close_and_reopen(tmp_path):
    path = tmp_path / "state.sqlite"
    first = StateDB(path)
    assert first.get("run") is None
    first.put("run", b"a durable run")
    first.close()
    second = StateDB(path)
    assert second.get("run") == b"a durable run"
    second.close()


def test_state_integrity_is_checked_before_return(tmp_path):
    database = StateDB(tmp_path / "state.sqlite")
    database.put("run", b"original")
    with database.connection:
        database.connection.execute("UPDATE state SET value=? WHERE key=?", (b"changed", "run"))
    with pytest.raises(ValueError, match="checksum"):
        database.get("run")
    database.close()


def test_state_rejects_oversized_payload_without_replacing_previous(tmp_path):
    database = StateDB(Path(tmp_path) / "state.sqlite")
    database.put("run", b"original")
    with pytest.raises(ValueError, match="limit"):
        database.put("run", b"x" * (16 * 1024 * 1024 + 1))
    assert database.get("run") == b"original"
    database.close()


def test_state_has_one_writer_and_releases_ownership_on_close(tmp_path):
    path = tmp_path / "state.sqlite"
    first = StateDB(path)
    with pytest.raises(OSError, match="in use"):
        StateDB(path)
    first.put("run", b"preserved")
    first.close()
    second = StateDB(path)
    assert second.get("run") == b"preserved"
    second.close()
