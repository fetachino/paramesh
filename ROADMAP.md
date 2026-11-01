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
- [ ] Exercise image builds and container training on a running Docker engine.
- [ ] Confirm remote CI in a clean checkout; add transitive dependency locking and audit.
- [ ] Define coordinated checkpoint epochs and a quiescence/fencing protocol.
- [ ] Implement safe local checkpoints, integrity checks, optimizer/receipt persistence and restore.
- [ ] Automate killed-worker/rejoin and killed-shard/restore scenarios across processes.
- [ ] Add SeaweedFS S3 checkpoint storage, then Azure SDK/Azurite tests.
- [ ] Measure RPC latency, byte counts, throughput, convergence and failure recovery;
      export JSON/CSV and record hardware/configuration/source metadata.
- [ ] Add compression only after the uncompressed baseline is measured.
- [ ] Add optional NATS lifecycle events without using it for gradient traffic.
- [ ] Instrument Prometheus metrics, OpenTelemetry context propagation and structured lifecycle logs.
- [ ] Exercise Grafana, Tempo and Loki against real training runs.
- [ ] Build a focused dashboard from real coordinator/shard/worker state.
- [ ] Capture reproducible, genuine screenshots under `docs/images/` once visible features exist.
- [ ] Add OpenBao and Keycloak only after core recovery and the trust model are tested.
- [ ] Validate OpenTofu/self-hosted deployment, then Coolify and k3s on available free compute.
- [ ] Audit documentation claims, clean-clone setup, storage/failure tests and visual evidence
      before a portfolio release. No `v1.0.0` tag is justified yet.

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

The next priority is coordinated checkpoint and recovery correctness, not adding
more infrastructure to an in-memory core.
