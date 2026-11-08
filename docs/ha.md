# Optional coordinator failover

The default coordinator uses a local checksummed SQLite state file and is intentionally single-host.
For an active/passive coordinator pair, install the `ha` extra and point both coordinators at the
same PostgreSQL database:

```powershell
uv sync --locked --extra ha
$env:PARAMESH_POSTGRES_DSN = "postgresql://..."
paramesh coordinator --config config.json --postgres-dsn $env:PARAMESH_POSTGRES_DSN
```

The PostgreSQL backend stores the same coordinator record and acquires a session-scoped advisory
lock. A second coordinator fails closed while the primary session is alive; after the primary
connection closes, a replacement can acquire the lock and recover the durable record. The backend
is opt-in and does not change the SQLite default.

This is active/passive coordinator failover, not a replicated PostgreSQL service or a claim of
zero-downtime high availability. The database itself must be durable and independently protected;
the free local Docker test only verifies fencing and state recovery.

The local recovery harness also verifies coordinator process replacement during an active
synchronous run: workers reconnect to the replacement endpoint, shards fence the old generation,
and the run completes with matching shard versions and the existing numerical reference check.
This is single-host process-failure evidence, not a claim of cross-region availability.

## Disposable PostgreSQL replication evidence

Run the real two-node streaming-replication check with Docker (it creates and removes only
temporary containers, volumes, and a network):

```powershell
uv run python scripts/verify_postgres_replication.py `
  --output artifacts/postgres-ha-local.json
```

The verifier starts two `postgres:17-alpine` nodes, creates a replication role, takes a physical
standby base backup, confirms `pg_stat_replication` reports `streaming`, stops the primary,
promotes the standby, and verifies both the pre-failover and post-promotion rows. The sanitized
result from the validated run is [preserved here](evidence/postgres-ha-local-20261108/results.json)
with SHA-256 `788d71987f07c652b3c51772441c960d5438ef190daca0fa83b02aeb9ef3a97c`.

This closes database replication and promotion evidence for the disposable Docker topology. It
does not yet close the ParamMesh release gate: coordinator replacement must still be exercised
against the promoted endpoint while a real training run is active, including worker reconnect,
checkpoint continuity, and an explicit stop condition for any mixed-version state.
