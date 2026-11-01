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
