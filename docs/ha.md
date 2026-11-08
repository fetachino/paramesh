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

The existing SQLite harness verifies coordinator process replacement during an active synchronous
run. The PostgreSQL-backed harness in
`artifacts/postgres-training-failover-20261108/` extends that check through a promoted database.
The validated run re-registered both workers at generation 2, published a post-failover
checkpoint at global step 8 with equal shard versions, and completed training at step 80 with
equal shard versions. This closes the disposable single-host active-training failover evidence;
it is not a claim of replicated production PostgreSQL HA or cross-region availability.

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

This closes database replication and promotion evidence for the disposable Docker topology. The
active-training coordinator replacement and checkpoint continuity check is preserved separately
above; production database redundancy and cross-host availability remain out of scope.

The provider-neutral production prerequisites and failover procedure are in the
[production PostgreSQL HA readiness runbook](production-postgres-ha.md). That
runbook is preparation only; it does not claim that the current single-node
production deployment has been migrated.
