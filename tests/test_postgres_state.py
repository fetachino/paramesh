import os

import pytest

from paramesh.postgres_state import PostgresStateDB


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
