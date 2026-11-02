# ADR-0001: Coordinate online checkpoint epochs through quiescence and fencing

## Status

Accepted. Authenticated live export, durable epoch fencing, and sync/async/bounded
integration tests are implemented. Fault injection covers requested timeouts, partial shard
freeze, uncertain manifest publication, partial unfreeze, abort/resume restarts, and active
worker-process restart from its durable journal. Coverage is summarized in the
[roadmap](../../ROADMAP.md).

## Date

2026-11-02

## Context

Each shard durably commits its own parameters, version and receipts. Each worker
durably journals a complete set of shard requests before sending any of them. The
coordinator separately persists membership, generations and reported progress.
These independent SQLite commits make process restart and replay safe, but do not
make a live cross-process snapshot atomic. The existing exporter obtains an offline
cut by taking exclusive state leases after all training processes stop.

An online checkpoint must prevent any worker or old session from advancing any
shard between the captured role records. It must preserve existing synchronous,
asynchronous and bounded-staleness training semantics and the current authenticated
administrative boundary. Object-store manifest publication is already immutable
and conditional; storage credentials should stay in the checkpoint helper.

## Decision

Use a coordinator-owned, monotonically increasing checkpoint epoch. An authenticated
admin caller requests an epoch and supplies its immutable checkpoint ID. The epoch
is persisted by the coordinator before a pause request is exposed to workers.
Repeating a request for an in-progress checkpoint ID returns that reserved epoch;
an aborted ID cannot be reused for a new epoch.

The epoch advances through `REQUESTED`, `FROZEN`, `COMMITTED`, and `RESUMING` before
returning to `RUNNING`:

1. In `REQUESTED`, fixed-membership workers finish their current iteration and
   finish all shard RPCs. Each worker then has an empty pending-request journal,
   stops starting steps, and acknowledges the epoch with its generation and durable
   next step. A worker that cannot reach this boundary prevents a checkpoint; it is
   not silently omitted.
2. After every configured worker has acknowledged, the coordinator freezes each
   shard using an idempotent epoch fence. A shard persists the highest accepted
   epoch and its frozen state, and rejects gradient writes while frozen. Unfreeze
   clears only the frozen state; the highest accepted epoch never moves backward.
   Freeze and update admission share the shard's update lock, so an update cannot
   race past the fence. The coordinator
   enters `FROZEN` only after every shard confirms its durable fence.
3. While all shards remain frozen and all workers remain paused, the checkpoint
   helper reads the coordinator record, every shard snapshot and every worker
   journal through admin-only snapshot RPCs. It validates membership, generations,
   empty worker journals, shard receipts and per-worker/per-shard progress, then
   writes content-addressed blobs and conditionally publishes the immutable
   manifest. The manifest records the epoch, each worker's next step and each
   shard's actual version; it does not infer equal progress from a global minimum.
4. After the manifest is confirmed, the coordinator records `COMMITTED`, unfreezes
   every shard idempotently, records `RESUMING`, and tells workers to continue. No
   worker resumes until every shard confirms release.

The epoch is a control-plane fence, not a new training step or optimizer version.
Synchronous workers will normally acknowledge the same step; asynchronous modes
may acknowledge different steps. The manifest preserves those exact values.
Existing online crash recovery and journal replay remain unchanged. This protocol
cuts only at a completed worker-step boundary, so it does not export an in-flight
partial delivery; the offline exporter continues to support those durable partial
steps today.

## Failure and restart behavior

- Missing, unavailable or non-acknowledging membership prevents entry to `FROZEN`;
  no partial membership checkpoint is published.
- Freeze requests, unfreeze requests and status reads are idempotent for the same
  epoch. A shard rejects stale epochs and cannot clear a newer fence.
- If some shards freeze and another is unavailable, workers remain paused and the
  coordinator retains the requested epoch. An operator may retry or explicitly
  abort; abort is complete only after all shards confirm unfreeze.
- After restart, persisted epoch state is authoritative. A coordinator or shard
  must not assume `RUNNING` when the stored phase is incomplete. Workers remain
  fenced until an admin retries commit/abort or completes resumption.
- If object publication may have succeeded but its response was lost, retry the
  same checkpoint ID and verify the immutable manifest contents before resuming.
  A conflicting manifest is an error; it is never overwritten.
- Training workers receive pause/resume control through a versioned control RPC or
  heartbeat response. The implementation must preserve the existing heartbeat
  contract for older clients or explicitly reject unsupported protocol versions.

## Alternatives considered

### Keep checkpoints offline-only

This is the current behavior and remains the fallback until the protocol is
implemented. It is safe and simple, but requires stopping all training services.

### Snapshot each live SQLite database independently

Rejected: role records could describe different points in training, and a worker
could have committed a subset of its journaled requests. A valid checksum would not
make the combined cut consistent.

### Pause only at a synchronous barrier

Rejected: it does not cover asynchronous and bounded-staleness modes, which are
supported parts of the current system.

### Let the coordinator hold all object-store credentials and publish directly

Rejected: storage credentials would move into a long-running training service.
The checkpoint helper already owns storage adapters and should remain the only
component receiving those credentials.

## Consequences

- Implementation requires versioned control-plane RPCs, durable coordinator epoch
  state, durable shard freeze epochs, worker safe-point acknowledgments, and a
  checkpoint helper that validates a frozen live cut.
- Epoch retries and explicit abort/recovery states add protocol and operator
  complexity. A stuck epoch fails closed by pausing training rather than exporting
  an inconsistent checkpoint.
- The existing offline checkpoint contract, CLI and partial-step restore behavior
  remain supported alongside online epoch checkpoints.
- Live checkpoint claims are limited to the tested fixed-membership protocol and failure
  matrix. Restarted coordinator sessions require worker processes to restart from their
  durable journals. No coordinator consensus, uninterrupted old-session continuity, or
  cloud durability guarantee is implied.

## Implementation acceptance

- Run synchronous, asynchronous and bounded-staleness two-worker/two-shard jobs;
  checkpoint a live epoch, restore it into fresh state, resume to completion and
  compare synchronous parameters with uninterrupted local SGD.
- Prove workers cannot start a later step after acknowledging, shard freezes wait
  for in-flight updates, and frozen shards reject writes from both current and stale
  generations.
- Inject coordinator/helper restarts and failures after worker pause, partial shard
  freeze, complete freeze, uncertain manifest publication and partial unfreeze.
  Each retry must preserve one immutable manifest and remain paused/fenced until all
  shards and workers agree on abort or resume.
- Verify data credentials cannot invoke control/snapshot methods; only the
  checkpoint helper receives object-store credentials.
- Keep the existing offline S3, Azure, local-store and partial-step replay tests
  passing, and retain the current Compose operations stack.
