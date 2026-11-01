# Verification evidence

Captured on November 1, 2026. These are actual native CPU runs and local checks;
they do not establish a cloud deployment or durable failure recovery.

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

No screenshots are included yet because there is no running dashboard or
observability UI to capture honestly.

## Local container verification

Docker Desktop was started successfully and reported engine version 29.7.2.
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
