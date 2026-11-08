# Roadmap

The supplied project brief is the long-term target. This checklist reports actual
implementation boundaries, not a claim that infrastructure examples are deployed.

## Product maturity levels

These levels describe the product path without moving or overwriting released tags:

| Level | Meaning | Status |
| --- | --- | --- |
| **1 · Foundation** | Recovery-first distributed CPU training, operations, hosted validation, immutable deployment, and the stable `v1.0.0` release. | **Complete** |
| **2 · Usability** | External PyTorch workload support, reproducible comparisons, clean-clone onboarding, dashboard evidence, and simple local evaluation. | **Implemented; external-user validation remains** |
| **3 · Team adoption** | Evidence that several real teams can use the workflow, stable configuration/data guidance, support boundaries, and only then justified integrations or paid services. | **Next** |

Level 3 is not a plan to add Kubernetes, GPUs, high availability, or a hosted
service by default. Those are decisions gated by observed user needs. The first
Level 3 deliverable is structured feedback from several independent researchers
or small teams using the documented workflow.

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
- [x] Extend the controlled topology beyond the initial two-host baseline with an
      experimental four-worker private-VPC run; the completion/equal-state record
      is in [the four-worker evidence](docs/evidence/benchmarks/gcp-multihost-4worker-2026-11-08/README.md).
- [x] Add repeated four-worker performance and fault-timing measurements with raw
      JSON/CSV, checksums, and explicit workstation limitations.
- [x] Extend the local controlled scaling matrix to 1/2/4/8 workers with three
      repetitions and deterministic reference checks; see the
      [clean-source evidence](docs/evidence/benchmarks/scaling-matrix-main-2026-11-08/README.md).
- [x] Prepare and verify private host addressing, RPC mTLS, NATS TLS, remote metrics targets and persistent role restart on an isolated Docker bridge; this is a single-host simulation only.
- [x] Run an actual two-VM Google Cloud private-VPC deployment with cross-host training,
      observability, controlled live checkpoint publication/restore validation and process restart;
      [completed checkpoint-gate evidence](docs/evidence/gcp-multihost-919bc0-20261104/README.md).
- [x] Add configurable larger-payload loopback measurements while retaining numerical-reference checks.
- [x] Measure uncompressed network/payload behavior before making a compression decision;
      compression remains deferred because the measured small workload is not network-bound.
- [ ] Add compression only when measured payload/network bottlenecks justify it;
      current larger-payload and private-VPC measurements do not yet establish that
      bottleneck.
- [ ] Deploy and validate a durable two-node production PostgreSQL topology;
      the provider-neutral [readiness runbook](docs/production-postgres-ha.md)
      is preparation only and the current hosted deployment remains single-node.
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
- [x] Validate the hosted dashboard hostname, trusted HTTPS, Secure session cookie,
      authentication and public/private service routing on the actual VM;
      see [evidence](docs/evidence/gcp-hosted-https-2026-11-03/README.md).
- [x] Verify a compatible hosted image rollback. The [immutable deployment
      workflow](docs/immutable-deployment.md), guarded procedure,
      [local-image validation](docs/evidence/gcp-hosted-rollback-2026-11-04/README.md)
      and [GHCR validation](docs/evidence/gcp-ghcr-rollback-2026-11-04/README.md)
      verify digest identity, OCI/Linux pull behavior, raw checkpoint preservation
      and retained-state isolated rollback. The [authorized live exercise](docs/evidence/gcp-live-rollback-2026-11-04/README.md)
      restored the original GHCR digest with equal shard versions and retained state.
- [x] Reproduce and fix the high-rate synchronous checkpoint completion race in a
      controlled local two-worker/two-shard process test; preserve repeated runs,
      failure/recovery coverage and numerical correctness evidence.
- [x] Retest the fixed protocol on separate Google Cloud hosts under the original
      high-rate workload, preserve raw traces/logs and close the distributed
      checkpoint barrier gate; see [evidence](docs/evidence/gcp-multihost-919bc0-20261104/README.md).
- [x] Publish the stable `v1.0.0` source release and its digest-qualified GHCR
      image after exact-source verification; see [release notes](docs/releases/v1.0.0.md).

## Post-v1 adoption path

The first release is intentionally focused on a small, inspectable CPU topology.
The next work should improve adoption around the same recovery-first product
boundary before adding GPUs, Kubernetes or high availability:

- [x] Define a stable external PyTorch model/training interface and preserve the
      bundled MLP as the deterministic reference workload.
- [x] Verify the external workload interface with deterministic linear, small CNN,
      and small transformer CPU examples; keep arbitrary-model support out of the
      contract.
- [x] Add one end-to-end example using an external model, with numerical
      correctness evidence; checkpoint and worker-restart coverage remain in the
      shared API and recovery suites.
- [x] Provide a one-command local quickstart that creates ignored credentials,
      starts the self-hosted stack and links to the operator checks.
- [x] Provide a reproducible external-workload comparison benchmark for sync,
      async and bounded-staleness modes with raw artifacts and charts.
- [x] Provide a no-Docker Windows local evaluation executable while retaining the
      Docker Compose operations path for persistent/team deployments.
- [ ] Validate the workflow with several research or small-team users before
      committing to GPU, scheduler or managed-service features.
- [ ] Evaluate paid deployment, support and integration services only after the
      external-model workflow has adoption evidence.

## Level 3 · Team adoption gates

- [ ] Recruit and document feedback from at least three independent research or
      small-team users using the clean-clone or standalone workflow; current
      sanitized registry: [0 / 3](docs/evidence/adoption/README.md).
- [ ] Record the first-run success rate, setup time, workload shape, recovery
      expectations, and blockers without collecting private data or credentials.
- [ ] Convert repeated feedback into a small supported-contract document: tested
      Python/OS/CPU combinations, model/workload constraints, state/backups, and
      operational limits.
- [ ] Add only the highest-value adoption fixes justified by that evidence.
- [ ] Revisit paid support, integrations, GPU scheduling, or managed hosting only
      after the adoption evidence supports a specific user-funded need.

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
records the native x86-64 Coolify run. The [two-host evidence](docs/evidence/gcp-multihost-919bc0-20261104/README.md)
records the completed private-VPC checkpoint gate on separate x86-64 Linux VMs. The [local ARM64 validation](docs/arm64-validation.md)
exercises that architecture under emulation; native ARM64 remains open. Oracle
Always Free A1 remains a future option if capacity returns.

Dependency locking, the [controlled local baseline](docs/evidence/benchmarks/uncompressed-local-2026-11-02/README.md),
[larger-payload loopback trial](docs/evidence/benchmarks/uncompressed-wide-sync-local-2026-11-02/README.md),
and Azure/Azurite checkpoint portability are complete. The tiny baseline model
does not establish a bandwidth bottleneck; larger-payload loopback measurements
are available but do not substitute for controlled network measurements, so
compression remains deferred. The hosted VM consumes promotional credit while running;
the live hosted rollback gate is closed. Final release-image publication and
provenance verification remain separate from the release candidate.
