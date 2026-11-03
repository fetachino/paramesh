# Roadmap

The supplied project brief is the long-term target. This checklist reports actual
implementation boundaries, not a claim that infrastructure examples are deployed.

- [x] Python packaging, generated protobuf tooling, local checks and CI definition.
- [x] Coordinator registration, fixed membership, heartbeat leases and status RPCs.
- [x] Deterministic ownership, validated float32 transport and atomic shard-local SGD.
- [x] Independent CPU PyTorch workers and a multi-process gRPC demo.
- [x] Fixed-membership synchronous barriers, mean/sum, local numerical reference.
- [x] Async updates and per-shard bounded-lag rejection with worker refresh.
- [x] Concurrent duplicate-delivery and local failure-path tests.
- [x] Separate-container Compose definition and syntax validation.
- [x] Complete local image build, authenticated container training and persistent recreation.
- [x] Confirm passing remote quality/container jobs and a package advisory audit.
- [x] Add reproducible transitive dependency locking for supported Windows/Linux Python 3.12 environments.
- [x] Define coordinated checkpoint epochs and a quiescence/fencing protocol in [ADR-0001](docs/decisions/0001-coordinated-checkpoint-epochs.md).
- [x] Implement authenticated online checkpoint epochs, durable shard fences, and sync/async/bounded live export with restore/resume.
- [x] Inject and recover checkpoint failures in REQUESTED, partial shard freeze, FROZEN, COMMITTED, RESUMING and ABORTING; restart coordinator/shards and an active worker from durable state.
- [x] Persist local parameters, optimizer configuration, receipts, worker journals and run metadata.
- [x] Automate killed-worker/rejoin and killed-shard/restart scenarios across processes.
- [x] Authenticate internal RPC roles, fence old generations and test optional TLS/mTLS.
- [x] Export whole-run checkpoints and validate offline restore, including partial steps.
- [x] Add local and authenticated SeaweedFS S3 checkpoint storage with immutable publication.
- [x] Add Azure Blob checkpoint storage and actual authenticated Azurite/SDK restore tests.
- [x] Measure local uncompressed RPC latency, byte counts, throughput and loss;
      preserve raw JSON/CSV, charts, hardware/configuration/source metadata.
- [ ] Extend controlled measurements to multi-host scaling and repeated faults.
- [x] Prepare and verify private host addressing, RPC mTLS, NATS TLS, remote metrics targets and persistent role restart on an isolated Docker bridge; this is a single-host simulation only.
- [x] Run an actual two-VM Google Cloud private-VPC deployment with cross-host training,
      observability, controlled live checkpoint publication/restore validation and process restart;
      [evidence and high-rate checkpoint limitation](docs/evidence/gcp-multihost-2026-11-03/README.md).
- [x] Add configurable larger-payload loopback measurements while retaining numerical-reference checks.
- [ ] Add compression only when measured payload/network bottlenecks justify it.
- [x] Add optional NATS lifecycle events without using it for gradient traffic.
- [x] Instrument Prometheus metrics, OpenTelemetry context propagation and structured lifecycle logs.
- [x] Exercise Grafana, Tempo and Loki against real training runs.
- [x] Build a focused dashboard from real coordinator/shard/worker state.
- [x] Capture genuine cluster, recovery, checkpoint, bounded-lag, Grafana and trace screenshots.
- [x] Validate the shared Compose stack locally and document Git-backed Coolify settings.
- [x] Assess additional identity/secrets infrastructure against the current private single-operator model;
      defer OpenBao/Keycloak until actual target requirements justify them.
- [x] Validate the shared stack through Coolify on one Google Cloud x86-64 Linux VM,
      including training, observability, checkpoint restore and retained-state restart.
- [x] Audit local documentation claims, clean-clone setup, storage/failure tests,
      package/security checks and preserved visual evidence; see [readiness audit](docs/release-readiness.md).
- [ ] Validate actual hosted HTTPS, isolation and rollback before a production release.
      No `v1.0.0` tag is justified yet.

## Intended cloud portability

These are architectural categories to evaluate, not current integrations or claims
of having deployed their managed equivalents.

| Planned self-hosted option | Cloud category |
| --- | --- |
| SeaweedFS S3 / Azurite | S3-compatible objects / Azure Blob |
| Coolify / k3s | Application orchestration / managed Kubernetes |
| OpenBao / Keycloak | Secret management / identity provider |
| Prometheus, Grafana, OpenTelemetry, Tempo, Loki | Metrics, logs and tracing |
| NATS | Operational messaging |
| OpenTofu / Traefik | Infrastructure as code / ingress |

The first hosted target is a Google Cloud Free Trial `e2-standard-2` VM with a 50 GiB
persistent disk. [Single-host evidence](docs/evidence/gcp-single-host-2026-11-03/README.md)
records the native x86-64 Coolify run. The [two-host evidence](docs/evidence/gcp-multihost-2026-11-03/README.md)
records private-VPC operation on separate x86-64 Linux VMs. The [local ARM64 validation](docs/arm64-validation.md)
exercises that architecture under emulation; native ARM64 remains open. Oracle
Always Free A1 remains a future option if capacity returns.

Dependency locking, the [controlled local baseline](docs/evidence/benchmarks/uncompressed-local-2026-11-02/README.md),
[larger-payload loopback trial](docs/evidence/benchmarks/uncompressed-wide-sync-local-2026-11-02/README.md),
and Azure/Azurite checkpoint portability are complete. The tiny baseline model
does not establish a bandwidth bottleneck; larger-payload loopback measurements
are available but do not substitute for controlled network measurements, so
compression remains deferred. The hosted VM consumes promotional credit while running;
public HTTPS, hosted rollback and real multi-host measurements remain open.
