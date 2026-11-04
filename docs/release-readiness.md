# Local release-readiness audit

The November 2, 2026 UTC audit verifies the local development system. A separate
[November 3 hosted run](evidence/gcp-single-host-2026-11-03/README.md) verified one
Google Cloud Linux VM. Neither result justifies a production `v1.0.0` release.
[The machine-readable record](evidence/release-readiness.json) preserves exact source,
dependency/package hashes, test results, CI identities and retained-service state.

## Verified boundaries

A fresh GitHub clone at `add0356d7c60d4e079ba0b2984e4e3db4124f2d7`
(merged as `30240275de91f0b022ed6affaa986178f40d5f5f`) installed all extras into a new
environment using uv 0.13.6 and the committed lock. All 117 tests passed without
skips/failures/errors, with 92.00% coverage against the 90% gate. This includes real
authenticated gRPC training, process recovery, local/SeaweedFS/Azurite checkpoints,
partial-step journal replay, TLS/role enforcement and dashboard validation.

Lint, formatting, strict types, generated protocol, JavaScript syntax, dependency
compatibility and Compose configuration checks passed. Independent exact-head CI
runs [41388822098](https://github.com/fetachino/paramesh/actions/runs/41388822098) and
[41388817261](https://github.com/fetachino/paramesh/actions/runs/41388817261) passed
quality and actual container/operations checks. A fresh wheel installation with
storage extras passed isolated imports, CLI version and dependency checks. Both
wheel and source distribution exclude ignored local content and credentials.

The OSV package audit found zero known advisories across 86 installed packages.
Public local documentation links resolve; tracked files contain none of the configured
local service credentials. These targeted checks are not a penetration test or an
exhaustive audit of every historical secret. Python packages are locked; base OS
layers and mutable image tags are not a bit-for-bit container lock.

All ten recorded screenshots retain their recorded hashes. The nine-trial baseline's
15 captured artifacts/lock snapshot preserve their checksums in the Git index and a
fresh checkout. Historical development artifacts retain their original provenance
and limitations. No capture was edited to improve its result.

The existing shared operations stack remains running: coordinator, both shards,
dashboard, SeaweedFS, NATS, Prometheus, Grafana, Loki and Tempo. Both completed workers
remain exited successfully. An authenticated readiness probe reached the retained
telemetry backends. Default volumes and running containers were not recreated for
the audit. Fresh test containers owned by verification runs were removed separately.

The audit found one Windows generation issue: Grafana JSON was logically unchanged
but emitted CRLF despite the repository's LF contract. The generator now selects LF
explicitly; regeneration is byte-identical to committed dashboard JSON.

## Remaining decisions and deployment gate

- **Compression:** deferred. The measured gradient is 196 raw tensor bytes and the
  local baseline does not establish a bandwidth bottleneck. Larger-payload and
  controlled-network measurements must justify a codec and its accuracy/CPU costs.
- **Secrets/identity/orchestration:** OpenBao, Keycloak, OpenTofu and k3s remain
  conditional options. The current private single-operator stack has no demonstrated
  need for additional identity infrastructure; adding undeployed templates would not
  validate portability. Reassess against an actual target and operator requirements.
- **Coolify:** the Git-backed stack ran on one Google Cloud Free Trial Linux VM with
  persistent volumes, private dashboard/Grafana access, a completed 1,000-step run,
  local and S3-compatible checkpoint restore, and retained-state restart.
  [The deployment runbook](coolify.md) records setup and remaining validation.
  [Public HTTPS verification](evidence/gcp-hosted-https-2026-11-03/README.md)
  now covers trusted TLS, the dashboard login, Secure cookies and the public
  routing boundary. [Hosted rollback investigation](evidence/gcp-hosted-rollback-2026-11-03/README.md)
  established a root-only backup and an isolated immutable-image smoke test.
  The [immutable deployment workflow](immutable-deployment.md) now records
  digest-qualified image identity and guards rollback compatibility. The
  [2026-11-04 validation](evidence/gcp-hosted-rollback-2026-11-04/README.md)
  verified an equal-shard checkpoint archive and retained-state isolated rollback;
  registry-backed publication and an approved Coolify production cutover remain
  open.
- **Protocol/model limits:** CPU float32 and the bundled fixed workload; offline
  whole-run checkpoints with the original topology; no coordinator consensus or
  replicated live state. Azurite compatibility is not managed Azure durability.

Before a public release, publish a digest-qualified image, verify hosted rollback
and preserve an offline
checkpoint and the deployed source/image identity before a rollout. Roll back code
only to a compatible version; state rollback is an offline whole-run restore into
fresh volumes, never mixing old shards with live peers. No hosted rollback duration
or service-level objective is claimed from local tests.
