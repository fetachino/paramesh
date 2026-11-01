# Durable recovery design

## Recovery boundary

The design preserves committed shard updates rather than rolling a live cluster
back to independently saved snapshots. A worker can die between shard pushes.
For synchronous training, recomputing the unfinished gradient from a partially
updated model would change the objective compared with uninterrupted SGD.

Therefore the recovery path has two durable records:

1. A shard commits parameters, optimizer configuration, version, receipts and
   worker-generation fences in one checksummed SQLite record before replying.
2. A worker journals its entire gradient request set before the first push.
   After restart, it reads shard progress and retries only unfinished contributions
   using the original bytes. Already acknowledged contributions remain immutable.

SQLite uses WAL and `synchronous=FULL`; storage write failures must leave both
weights and receipts unchanged in memory. This favors correctness over throughput.
The optimizer is currently stateless SGD, so its complete state is its validated
configuration plus authoritative weights. Momentum/Adam must add their extra tensors
to the same transaction before being supported.

## Membership and fencing

Coordinator metadata persists the run configuration and monotonically increasing
worker generations. A replacement receives a new generation only after the old
lease expires. Registration fences that generation on every shard before the new
worker can send updates. Old in-flight gradients are rejected after fencing;
pending barriers are aborted so surviving workers can retry their saved requests.

Transport fingerprints omit generation metadata, allowing the same semantic update
to be retried by a replacement incarnation without a second optimizer step. Run,
worker, step, base version and gradient contents remain part of the fingerprint.

The coordinator's session token is not persisted as a usable lease across process
restart. Workers re-register and receive fresh fencing generations. Completed
progress remains part of durable metadata. Coordinator process recovery must not
reset generation counters or silently accept a different run configuration.

## Checkpoints and storage portability

A checkpoint is a manifest plus checksummed, safe-format shard snapshots and the
worker journals needed to finish a partially delivered step. It records actual
per-shard versions, receipts, optimizer configuration and a completed-step lower
watermark. It must not label unequal shard versions as one atomic model version.

Normal shard process restart uses the latest committed local database. Restoring
an older exported checkpoint is a separate, offline operation affecting the entire
run. Mixing a restored old shard with unreverted live peers is unsupported.

Checkpoint stores expose immutable blob put/get and final manifest publication.
Local publication must be atomic; an S3-compatible backend publishes the manifest
only after all content-addressed objects are present. Azure Blob can implement the
same contract later. An incomplete upload is not a completed checkpoint.

## Verification sequence

- Domain persistence: reopen exact state, retry receipts, disk failure and corruption.
- Network recovery: durable registration, stale-generation rejection and journal resume.
- Process failure: terminate a worker after partial delivery, expire its lease,
  replace it and compare final synchronous weights with local SGD.
- Shard failure: terminate/restart the process against the same database and verify
  that acknowledged updates are neither lost nor applied twice.
- Storage restore: validate the complete manifest before starting a new run from it.

Implementation status is tracked in `tasks/todo.md`; this design document is not
evidence that every recovery path has passed yet.
