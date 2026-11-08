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
