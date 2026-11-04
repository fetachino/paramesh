# Verification evidence

Captured on November 1, 2026. These are actual native CPU runs and local checks;
they do not establish a cloud deployment. The original baseline remains below;
newer durable recovery artifacts are documented separately.

| Artifact | What it proves |
| --- | --- |
| [sync-cpu.json](sync-cpu.json) | Two workers/two shards, 20 synchronous steps, local-reference parameter error |
| [async-cpu.json](async-cpu.json) | Two workers/two shards, 40 committed updates per shard, completed worker runs |
| [bounded-cpu.json](bounded-cpu.json) | A real bounded-mode run with measured loss/version state |
| [verification.json](verification.json) | 41 passing tests, no skips, 93.39% statement coverage against a 90% gate |
| [dependency-audit.json](dependency-audit.json) | pip-audit/OSV found no known advisories across 54 installed packages |

Run reports contain their exact commit, dirty state and workload configuration.
Async/bounded artifacts were captured concurrently and are not performance comparisons.
The final test count is from source commit `86fe073`; it adds a test to the runtime
code used for the training artifacts. No weights, losses or version counters were
edited for presentation.

## Commands exercised

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python scripts/generate_proto.py --check
python -m pytest --cov --cov-report=term-missing --cov-report=json:artifacts/coverage.json --junitxml=artifacts/tests.xml -q
python -m build
python -m pip check
python -m pip_audit --vulnerability-service osv --format json --output artifacts/dependency-audit-updated.json
docker compose config --quiet
```

The wheel was also installed into a fresh virtual environment, then its version
command and service imports were exercised without the editable source install.
A temporary inversion of the staleness rejection condition caused the focused
regression test to fail, confirming that it detects the wrong acceptance rule;
the source was restored before final verification.

The bounded refresh test injects a competing update through actual shard logic
while a real gRPC worker has already committed to another shard. It verifies one
refresh and no duplicate application on the earlier shard. That controlled test
is distinct from the newer killed-process recovery demonstrations.

Generated bindings and the CLI dispatcher are excluded from coverage. The report
includes worker/server code executed by spawned processes. Native tests ran on
Windows. [The core CI record](ci-baseline.json) now records actual passing remote
quality and container jobs; the original baseline files above remain historical.

The genuine [CI screenshot](../images/github-actions.png) captures successful
quality and container jobs for `f92103a`, Actions run `41349354085`. It is an actual
browser screenshot, converted losslessly from the browser's JPEG to PNG; no status
text or results were altered. Later dashboard/observability captures are indexed below.

## Local container verification

The final recovery verification reported Docker engine version 29.9.2.
The interrupted 209.5 MB CPU-wheel download was completed using validated byte
ranges and matched the SHA-256 published by PyTorch:
`0955c7e3446326293f48af18fad67872fa31dee5a36a87690eb9e5be8b465be3`.
A temporary loopback mirror supplied those exact bytes to the normal Dockerfile;
normal Git-backed builds still default to the official CPU package index.

Local verification completed five-container training at step 20, enforced data/admin
credentials and denied unauthenticated parameter reads. No training service published
a host port. Recreating the services retained weights, versions and journals: workers
resumed from completed step 20 with empty new-loss histories, rather than retraining.
`scripts/verify_compose.py` reproduces these checks in a uniquely named project and
removes only that project's synthetic test volumes. Its report is written under
`artifacts/compose-verification.json`. No public deployment is claimed.

## Durable recovery milestone

[Worker termination](worker-recovery.json), [shard termination](shard-recovery.json)
and [Compose recreation](compose-recovery.json) were captured from clean source
`f92103a`. See [benchmark methodology](../../BENCHMARKS.md) for timing boundaries.
GitHub Actions runs `41349354085` and `41349349193` passed quality and container jobs
on that head before [PR #2](https://github.com/fetachino/paramesh/pull/2) was merged.

## Checkpoint storage

[The S3 contract report](s3-checkpoint.json) records an actual authenticated SeaweedFS
4.51 round trip with a partially delivered step (shard versions 1 and 0), conditional
manifest publication and restored worker journal. This artifact was produced during
development of the checkpoint milestone; its own manifest does not claim a clean
source commit or production benchmark. The native RPC restore test independently
resumes that partial cut and compares the final model with uninterrupted SGD.

[Azure checkpoint restore](azure-checkpoint.json) was captured from clean source
`ae2a445bcb348c3a85fdb87c6b9f60f9c12773a9` on November 2, 2026 UTC using the official
SDK 12.31.1 and digest-pinned Azurite 3.37.0, API `2026-06-06`. The actual offline
partial checkpoint has shard versions 1 and 0. After download/validation, real RPC
training replays one journaled contribution and reaches global step 4 with maximum
parameter error `1.19e-7` against uninterrupted SGD. Credentials are not included.
This verifies emulator compatibility; no managed Azure durability, performance or
deployment claim follows. [Operator documentation](../checkpoints.md#azure-blob-and-azurite)
describes the full disposable-container contract suite and its limitations.

## Operations integration

[Operations stack](operations-stack.json) records a separate fresh Compose project:
100 paced steps, actual Prometheus worker counters, Loki lifecycle records and an
eight-span worker/shard Tempo trace. The verifier checks private backend/data-plane
ports and removes only its own synthetic volumes. [Checkpoint rerun](compose-checkpoint-operations.json)
repeats local/S3 export, fresh-volume install and zero-work resume with the operations
code installed. Both reports honestly identify an uncommitted development tree.

[Bounded-lag operations](bounded-operations-stack.json) records a separate fresh
project with 1,000 completed worker iterations and 2,000 commits per shard. Its
accepted-staleness history stayed within the configured bound of 2; the maximum
sampled value was 1. This is a sampled operational observation, not an exhaustive
protocol proof or a performance comparison. [Native verification](operations-verification.json)
records 100 passing tests at 91.76% coverage and the package/static checks.

[Screenshots](../images/README.md) were captured from real local browser surfaces.
They show live or recorded evidence explicitly; no placeholder values or fabricated
public deployment are included. CI checks the exact committed heads independently.

## Uncompressed performance baseline

[Nine local trials](benchmarks/uncompressed-local-2026-11-02/README.md), captured on
November 2, 2026 UTC, preserve clean-source provenance, host CPU/RAM, exact lock,
21,730 raw client RPC observations, JSON/CSV and generated charts. Checksums are
verified in tests and captured bytes are protected against Git line-ending conversion.
These healthy single-host measurements are distinct from the historical correctness
and deliberately paced recovery evidence above.

[Larger-payload sync trials](benchmarks/uncompressed-wide-sync-local-2026-11-02/README.md)
use the same two-worker/two-shard correctness path with 31.4x larger raw gradient
payloads. They remain local loopback measurements and do not justify compression.

## Local readiness audit

[Readiness record](release-readiness.json) links a fresh GitHub clone/new locked
environment with 117 passing tests, 92.00% coverage, zero known OSV advisories across
86 installed packages, package checks, preserved screenshots/raw captures and the
retained operations stack. [Scope and remaining gates](../release-readiness.md)
distinguish the November 2 local audit from the later hosted deployment.

## Google Cloud single-host deployment

[The hosted evidence](gcp-single-host-2026-11-03/README.md) records a real
Coolify deployment on one Google Cloud x86-64 Linux VM, with raw training,
observability, checkpoint and restart records. It does not establish public
HTTPS, native ARM64 or separate-host scaling.

## Google Cloud two-host test

[The completed two-VM checkpoint evidence](gcp-multihost-919bc0-20261104/README.md)
records the exact source, private-VPC topology, repeated high-rate checkpoints,
equal shard versions, worker restart, genuine abort and post-abort publication,
raw manifest checksums, and direct numerical comparison. Historical runs remain
available in [the original two-host record](gcp-multihost-2026-11-03/README.md).
Hosted immutable rollback remains a separate release gate.

## Google Cloud hosted HTTPS rollout

[The HTTPS evidence](gcp-hosted-https-2026-11-03/README.md) records the later
single-host DuckDNS, Let's Encrypt, dashboard authentication and private routing
checks. It does not establish hosted rollback or resolve the high-rate barrier failure.

## Local high-rate synchronous checkpoint fix

[The local barrier evidence](checkpoint-barrier-local-20261103/README.md) records
the deterministic two-worker/two-shard reproduction, root cause, smallest fix,
repeated high-rate runs and existing abort/restart coverage. The completed
Google Cloud evidence above is the separate-host retest.

## Google Cloud hosted rollback investigation

[The rollback evidence](gcp-hosted-rollback-2026-11-03/README.md) records the
actual image identities, Compose behavior, root-only backup, archive hashes and
isolated candidate check. It does not claim a live rollback because the current
Coolify build is mutable-tag based and no prior Coolify rollback image exists.
