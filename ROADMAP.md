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
- [ ] Define coordinated checkpoint epochs and a quiescence/fencing protocol.
- [x] Persist local parameters, optimizer configuration, receipts, worker journals and run metadata.
- [x] Automate killed-worker/rejoin and killed-shard/restart scenarios across processes.
- [x] Authenticate internal RPC roles, fence old generations and test optional TLS/mTLS.
- [x] Export whole-run checkpoints and validate offline restore, including partial steps.
- [x] Add local and authenticated SeaweedFS S3 checkpoint storage with immutable publication.
- [x] Add Azure Blob checkpoint storage and actual authenticated Azurite/SDK restore tests.
- [x] Measure local uncompressed RPC latency, byte counts, throughput and loss;
      preserve raw JSON/CSV, charts, hardware/configuration/source metadata.
- [ ] Extend controlled measurements to larger payloads, multi-host scaling and repeated faults.
- [ ] Add compression only when measured payload/network bottlenecks justify it.
- [x] Add optional NATS lifecycle events without using it for gradient traffic.
- [x] Instrument Prometheus metrics, OpenTelemetry context propagation and structured lifecycle logs.
- [x] Exercise Grafana, Tempo and Loki against real training runs.
- [x] Build a focused dashboard from real coordinator/shard/worker state.
- [x] Capture genuine cluster, recovery, checkpoint, bounded-lag, Grafana and trace screenshots.
- [x] Validate the shared Compose stack locally and document Git-backed Coolify settings.
- [ ] Add OpenBao and Keycloak only after core recovery and the trust model are tested.
- [ ] Validate OpenTofu/self-hosted deployment, then Coolify and k3s on available free compute.
- [ ] Audit documentation claims, clean-clone setup, storage/failure tests and visual evidence
      before a release. No `v1.0.0` tag is justified yet.

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

Dependency locking and the first [controlled local baseline](docs/evidence/benchmarks/uncompressed-local-2026-11-02/README.md)
and Azure/Azurite checkpoint portability are complete. The tiny baseline model
does not establish a bandwidth bottleneck; compression remains deferred pending
larger-payload/network measurements. Actual Coolify deployment is pending
an available authorized server; no paid compute has been provisioned.
