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
is distinct from a killed-process recovery demonstration, which is not implemented.

Generated bindings and the CLI dispatcher are excluded from coverage. The report
includes worker/server code executed by spawned processes. Native tests ran on
Windows; remote GitHub Actions has not been exercised by this local work.

No screenshots are included yet because there is no running dashboard or
observability UI to capture honestly.

## Container verification limit

Docker Desktop was started successfully and reported engine version 29.7.2.
`docker compose config --quiet` passes. The image build reached dependency
installation, but the 209.5 MB Linux CPU PyTorch wheel download was interrupted
at 19.4 MB. An alternate official endpoint also interrupted at 5.2 MB. Both
attempts were canceled after establishing that the dependency download remained
unreliable. No application container was started and no container-training result
is claimed. Dockerfile dependency installation is cached separately from source
changes so subsequent application edits do not require another PyTorch download.
