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
- [ ] Add optional NATS lifecycle events; training continues while NATS is unavailable.
- [ ] Add Prometheus metrics and distributed tracing with real observability services.
- [ ] Build a focused operations dashboard over actual state and benchmark artifacts.
- [ ] Capture genuine dashboard, recovery, checkpoint, metrics, trace and CI evidence.
- [ ] Validate the same Compose definition for Git-backed Coolify and document server requirements.
- [ ] Continue Azure/Azurite, benchmarks, measured compression, secrets/identity and infrastructure work.

Each completed slice requires tests, lint/type checks, synchronized documentation,
a coherent commit and a push. No paid provisioning or unverified deployment claims.
The user authorized autonomous diff review, PR descriptions, CI fixes and merges;
do not ask the user to compare or approve ordinary project pull requests.
