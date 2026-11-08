# Production PostgreSQL HA readiness

ParamMesh currently supports an active/passive coordinator pair backed by
PostgreSQL, but the production deployment still has one PostgreSQL dependency.
The Docker replication and promoted-database training runs are disposable
verification only; they do not close this gate.

## Required topology

Use two durable Linux PostgreSQL nodes in the same private network, with:

- PostgreSQL 17 (or the exact version used by the primary), SCRAM authentication,
  encrypted private-node traffic, and persistent disks;
- primary-to-standby streaming replication with replication slots and WAL
  retention sized for the planned maintenance window;
- a private, health-checked writer endpoint that points to only the current
  primary; and
- backups independent of both nodes, with a tested restore before migration.

The coordinator's `PARAMESH_POSTGRES_DSN` must resolve to the writer endpoint,
not to a public address or a permanently fixed node. Workers and shards remain
on the existing private network. No PostgreSQL, shard, checkpoint, or worker
volume may be deleted or reinitialized during a failover test.

## Migration gate

Do not change the production DSN until all of these are recorded outside Git:

1. a consistent backup of the coordinator database, application SQLite state,
   worker journals, and checkpoint manifests;
2. replication is streaming and a known marker row is visible on the standby;
3. both nodes pass `pg_verifybackup`/restore checks for the selected backup
   method, and the rollback DSN is known;
4. coordinator and worker versions are identical and compatible with the
   existing checkpoint metadata; and
5. a maintenance window, stop conditions, and an operator with console access
   are present.

The first production exercise should be a controlled coordinator-only failover.
It must verify lease fencing, worker re-registration, a checkpoint after
promotion, equal shard versions, and no duplicate committed updates. It must
not restart completed workers or reset training state. If any worker remains
outside the healthy checkpoint-safe lease window, stop and restore the original
writer endpoint; do not widen deadlines to hide the failure.

## Recovery and limitations

The original primary remains the rollback target until the promoted node has
passed application checks. Record the exact PostgreSQL timeline/LSN, DSN
endpoint identity, coordinator generation, checkpoint manifest, shard versions,
and health results for both directions of the exercise. Restore the original
writer only after fencing the promoted writer and verifying that no writes are
still in flight.

This plan does not provide consensus, multi-region availability, automatic
split-brain prevention, or zero-downtime guarantees by itself. Those require a
reviewed failover controller or managed database service and a separate
authorization decision. Until a real two-node production topology passes this
procedure, ParamMesh must continue to document production PostgreSQL HA as
unverified.

