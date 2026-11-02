# ParamMesh implementation plan

The supplied ParamMesh brief defines the target system. This plan tracks local
implementation; a roadmap entry is not evidence of a working capability.

| Boundary | Responsibility | Depends on |
| --- | --- | --- |
| protocol | Versioned protobuf messages, bounded float32 tensor encoding | — |
| coordinator | Run identity, membership, heartbeat leases, shard endpoints | protocol |
| shard | Parameter ownership, validation, versioning, optimizer updates | protocol |
| worker | PyTorch forward/backward, pull/push, membership heartbeats | coordinator, shard |
| recovery | Durable coordinated checkpoints, fencing, restart tests | coordinator, shard, worker |
| operations | Metrics, traces, dashboard, genuine visual evidence | working core |
| deployment | Storage adapters, Compose, self-hosted infrastructure | verified services |

Build in that order. Supporting infrastructure stays outside the gradient path.

## First acceptance checks

- [x] Install on Python 3.12; lint, strict type checks, tests and isolated wheel import pass.
- [x] Regenerate checked-in protobuf code deterministically; CI is configured to detect drift.
- [x] Reject malformed, oversized, non-finite or wrongly shaped tensors before updates.
- [x] Verify deterministic sharding and worker health transitions with a controlled clock.
- [x] Exercise coordinator and shard APIs through actual gRPC channels with deadlines.
- [x] Train an actual CPU PyTorch model using separate worker and shard processes.
- [x] Compare synchronous updates with a mathematically equivalent local reference.
- [x] Record commands, limitations and genuine native run artifacts in documentation.

No paid services, deployment claims, invented measurements or fabricated screenshots.

## Runtime and recovery continuation

The next slices follow the user's explicit continuation request. Compose remains
the shared local/Coolify deployment definition; only the dashboard/API may
be public. Work is tracked in `tasks/todo.md`.

Recovery persists every shard commit (weights, optimizer configuration, version
and latest receipts) before acknowledging it. Workers journal gradient requests
before sending, so a crash after a partial multi-shard commit can resume the exact
uncommitted contribution. Re-registration fences the previous worker incarnation.
This avoids pretending that independently saved live shards form an atomic global
checkpoint. Checkpoint manifests must record each shard's actual version and progress;
offline restore of a complete manifest is separate from ordinary process restart.
The coordinated live-checkpoint path is implemented in
[ADR-0001](../docs/decisions/0001-coordinated-checkpoint-epochs.md): active workers
quiesce at durable step boundaries, shards persist fences, and the helper publishes
validated snapshots. Tests cover two workers/two shards in all three training modes,
restore/resume, auth boundaries, abort, immutable retry, a lost manifest response, and
partial unfreeze recovery after coordinator/shard restart. Additional tests cover timeout
and abort while REQUESTED, partial shard freeze, ABORTING/RESUMING restarts, and an active
worker process re-registering from its durable journal after coordinator restart. Live
claims remain limited to the tested fixed-membership healthy-worker path.

These foundations and the local operations stack are now implemented. Genuine visual
evidence and Git-backed Coolify instructions are committed with the deployment slice;
public verification is pending an authorized server. Dependency locking and the
first controlled uncompressed local baseline are complete. Azure/Azurite now reuses
the immutable checkpoint contract and verifies partial-step RPC resume. The host-based
Compose overlay now supports private endpoints, RPC mTLS, NATS TLS, remote Prometheus
targets, and per-host persistent volumes; its local segmented-network verification is
not a separate-host run. Larger-payload/network and repeated-fault measurements remain
separate future work.

Dependencies: verified containers → durable shard/worker/coordinator state → fencing
and authenticated RPCs → killed-process tests → checkpoint stores → events/telemetry
→ operations dashboard and genuine screenshots → validated Coolify instructions.
