# Continuation tasks

- [x] Verify Compose image build, service health, real training, clean stop/start and private ports in CI.
  - Verify: `docker compose build`, start all five containers, require both worker exit codes 0.
  - Passed: Actions run 41343758014 and local authenticated verification with persistent recreation.
- [x] Verify origin and push the existing branch without rewriting history.
- [x] Add durable shard commits with atomic weights/version/receipt storage.
  - Verify: restart from disk, reject mismatched/corrupt state, no memory mutation on write failure.
- [x] Journal worker requests and persist coordinator run/membership metadata.
  - Verify: resume a partially delivered step; reject stale worker incarnations.
- [x] Authenticate RPCs, separate administrative calls and add TLS/mTLS configuration.
  - Verify: missing/wrong credentials fail; data credentials cannot mutate administrative state.
- [x] Kill/restart workers and shards during real training; record detection, recovery and journal replay.
  - Verify: completed training and synchronous numerical-reference comparison after recovery.
- [x] Export/restore complete offline checkpoint manifests through local and S3-compatible stores.
  - Verify: checksums, failed/incomplete publication, local restore and actual SeaweedFS operations.
- [x] Define coordinated online checkpoint epoch, quiescence and fencing semantics in ADR-0001.
- [ ] Implement and fault-test online epochs; current checkpoint commands remain offline-only.
- [x] Add optional NATS lifecycle events; training continues while NATS is unavailable.
- [x] Add Prometheus metrics and distributed tracing with real observability services.
- [x] Build a focused operations dashboard over actual state and benchmark artifacts.
- [x] Capture genuine dashboard, recovery, checkpoint, metrics, trace and CI evidence.
- [x] Validate the same Compose definition locally and document Git-backed Coolify/server requirements.
- [ ] Deploy through Coolify and verify public HTTPS once an authorized server is available.
- [x] Lock transitive dependencies reproducibly for supported development/runtime platforms.
- [x] Add controlled uncompressed benchmarks with raw JSON/CSV, hardware/source metadata and charts.
  - Captured: nine clean-source local trials, exact lock snapshot and verified raw artifact checksums.
- [x] Add configurable larger-payload uncompressed benchmark trials with a synchronous numerical-reference gate.
  - Captured: three clean-source 4-256-1 loopback trials, 6,148-byte gradients, raw RPC records and verified checksums; multi-host/network evidence remains open.
- [x] Add Azure/Azurite checkpoint portability with actual partial-step RPC resume tests.
- [x] Evaluate whether the first baseline justifies compression: defer for the tiny 196-byte gradient.
- [ ] Revisit compression after larger-payload/network evidence, then justified infrastructure work.
- [x] Audit fresh-clone locked setup, packages, tests, documentation and preserved evidence.
  - Verified: 117 tests, 92.00% coverage; zero known OSV advisories across 86 packages.
  - Fixed: deterministic LF output from the Grafana generator on Windows.
- [ ] Verify actual hosted HTTPS, isolation and rollback on an authorized deployment target.

Each completed slice requires tests, lint/type checks, synchronized documentation,
a coherent commit and a push. No paid provisioning or unverified deployment claims.
The user authorized autonomous diff review, PR descriptions, CI fixes and merges;
do not ask the user to compare or approve ordinary project pull requests.
