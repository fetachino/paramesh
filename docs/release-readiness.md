# Release-readiness audit

The earlier November 4 audit covered the local development system and the
digest-qualified production cutover. A separate
[November 3 hosted run](evidence/gcp-single-host-2026-11-03/README.md) verified one
Google Cloud Linux VM. [The historical machine-readable record](evidence/release-readiness.json)
preserves that audit's source, dependency/package hashes, tests and CI identities.
The v1.0.0 candidate audit below supersedes its open rollback status.

## v1.0.0 candidate audit — 2026-11-04

The candidate starts from merged `main` at
`bf4f6de66109603b692d3e1ae49c839f463d924d`, containing PR #39's Windows
checkpoint barrier recovery fix and PR #38's immutable deployment guard.
PR #32's Community Standards change is merged. Main's CI run
[41905908244](https://github.com/fetachino/paramesh/actions/runs/41905908244)
passed quality and container jobs. The [authorized live rollback](evidence/gcp-live-rollback-2026-11-04/README.md)
temporarily ran four services on the original protected image and restored the
exact GHCR digest with equal shard versions, valid checkpoints, durable state,
authenticated HTTPS and stopped workers. The hosted rollback gate is closed.
Private backup contents and deployment logs remain outside Git.

Local candidate checks passed: locked Windows Python 3.12 ran **142 tests** with
**91.62% coverage** against the 90% gate; Ruff lint/format, strict mypy,
generated protocol, JavaScript syntax, lock freshness, dependency compatibility,
package build, wheel installation and immutable Compose validation passed.
The wheel and source distribution excluded ignored private material. A current
pip-audit/OSV query found zero known advisories among **87 installed packages**;
that is a point-in-time advisory result, not a container OS audit. Seven
protected deployment credentials were absent from tracked text files, public
relative Markdown links resolved, and GitHub private vulnerability reporting
was confirmed enabled. The [security policy](../SECURITY.md) now names that
private reporting route.

The local Linux x86-64 image built from a pinned Python base. Isolated Compose
training, RPC-role/private-port checks, retained-state restart and local/S3
checkpoint restore passed. An isolated operations stack verified authenticated
dashboard state and Prometheus/Tempo/Loki; the local multi-host network
simulation passed. The first Compose run inherited this PC's ignored `.env`
requesting 2,000 paced steps and exceeded its 180-second test wait. A repeat
with process-only `PARAMESH_STEPS=20` and `PARAMESH_STEP_DELAY=0` passed the
same assertions without changing credentials, test deadlines or source.

The candidate also built as `linux/arm64` and imported locked PyTorch, NumPy
and grpcio under QEMU. A standalone emulated demo exceeded its fixed child
startup deadline before training; the repository's ARM64 Compose validation
profile subsequently completed two workers at step 10 with shard versions
10/10, and its isolated resources were removed. This is emulated functional
evidence only; native ARM64 and ARM64 release-image publication are unverified.

The release image workflow now derives its tag, OCI revision, build date and
manifest from the **checked-out** exact commit, not the workflow event SHA when
manual `source_ref` differs. The Python Docker base is digest-pinned. The
[candidate notes](releases/v1.0.0.md) describe publication and independent
digest/provenance checks. Exact-head CI for this release-candidate PR, a build
from its eventual merged main SHA, registry pull and isolated image verification
remain gates **after** the PR. No new image or production deployment occurred
in this audit; the current hosted digest still comes from older source
`2b1fbae42a5ea15cfa3507baed5f25a2533af33c`.

## 2026-11-04 audit addendum

- `origin/main` is `4c28aa3e10fe6a5bf6cc8202c015f581502f934d` after PR #39 merged.
- Production runs the Linux/amd64 image
  `ghcr.io/fetachino/paramesh@sha256:31b6cb80d1fda851536e508cf38b593dcd1135b1fbf94f846c3d840aaba06ba1`,
  whose OCI revision is `2b1fbae42a5ea15cfa3507baed5f25a2533af33c`. Current
  `main` also contains PR #39's changes to worker deadline recovery, shard barrier
  cancellation and the gRPC adapter, plus regression tests and documentation. The
  production image predates those application-code changes; it has not been rebuilt
  or redeployed with PR #39. A release image must identify its own newer source SHA.
- The exact-head GitHub Actions CI run [41853757527](https://github.com/fetachino/paramesh/actions/runs/41853757527)
  passed both quality and container jobs. Local locked Ruff, formatting, mypy,
  generated-file, package-build and OSV audit checks also passed.
- Before PR #39, the full Windows suite reached 138 passed and 1 failed (91.20%
  coverage); the high-rate two-shard checkpoint test failed twice in five focused
  repetitions. PR #39 diagnosed hidden `PushGradients` deadline retries and a
  canceled-barrier cleanup race. After the fix, 10/10 repeated Windows trials and
  the full locked Windows suite (141 passed, 91.42% coverage) passed. Three Linux
  container regression tests and PR #39's exact-head quality/container CI passed.
  See the [Windows barrier evidence](evidence/checkpoint-barrier-windows-2026-11-04/README.md).
- The production cutover recreated only the running application roles with the
  digest-qualified image, left completed workers stopped, retained all named
  volumes, and verified HTTPS authentication, SQLite integrity, checkpoint blobs
  and worker-journal consistency. At the time of this earlier audit, no live
  rollback had been performed; the candidate audit above records its later pass.

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
  [2026-11-04 GHCR validation](evidence/gcp-ghcr-rollback-2026-11-04/README.md)
  verified registry publication, an exact Linux pull, equal-shard checkpoint
  preservation and retained-state isolated rollback. The approved Coolify
  production cutover is complete with the verified GHCR digest. The later
  [authorized live restoration](evidence/gcp-live-rollback-2026-11-04/README.md)
  closed that release gate.
- **Protocol/model limits:** CPU float32 and the bundled fixed workload; offline
  whole-run checkpoints with the original topology; no coordinator consensus or
  replicated live state. Azurite compatibility is not managed Azure durability.

Before a public release, merge the candidate with exact-head CI, build and
publish an image from the resulting merged commit, and independently verify its
registry digest, OCI revision, platform and isolated retained-state behavior.
Preserve an offline checkpoint and source/image identity before any future
rollout. Code rollback requires a compatible version; state rollback is an
offline whole-run restore into fresh volumes, never mixing old shards with live
peers. The live exercise measured no continuous outage or service-level objective.
