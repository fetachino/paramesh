# Linux ARM64 deployment gate

Oracle Cloud Always Free Ampere A1 remains one candidate for native Linux ARM64
deployment if capacity returns. The final Linux VM target is provider-flexible;
this page records local ARM64 validation only. No cloud account, VM, Coolify
resource or public endpoint was created.

## Local test on 2026-11-02

The host was Docker Desktop on Windows with a Linux AMD64 daemon and QEMU ARM64
emulation. `python:3.12-slim`, the digest-pinned uv image and all six pinned
infrastructure images had ARM64 manifests. The Python 3.12 lock was extended to
Linux `aarch64`; the application image built for `linux/arm64` and imported
PyTorch 2.15.0+cpu, grpcio 1.76.0 and NumPy 2.3.4 inside an ARM64 container.

The test used a separate Compose project and the
[`compose.arm64-validation.yaml`](../compose.arm64-validation.yaml) override.
That override pins every service to ARM64 and uses TCP startup probes for the
Python services because the normal 3–5 second CLI health probes exceeded their
timeouts under QEMU. The ordinary `compose.yaml` health checks were not changed.
The test project did not share the existing stack's volumes or networks.

```powershell
docker buildx build --platform linux/arm64 --load -t paramesh:arm64-validation .
$env:COMPOSE_FILE = 'compose.yaml;compose.arm64-validation.yaml'
$env:PARAMESH_DASHBOARD_PORT = '0'
$env:PARAMESH_GRAFANA_PORT = '0'
$env:PARAMESH_NATS_URL = 'nats://nats:4222'
$env:PARAMESH_OTLP_ENDPOINT = 'http://tempo:4318/v1/traces'
$env:PARAMESH_TRACE_SAMPLE_RATIO = '1'
$env:PARAMESH_STEPS = '10'
docker compose -p paramesh-arm64-complete --profile operations --profile storage up -d --no-build
```

The container manifest descriptors reported `linux/arm64` for the coordinator,
two shards, two workers, dashboard, SeaweedFS, NATS, Prometheus, Grafana, Loki
and Tempo. Both workers exited 0 after a retained-state run reached global step
10 with shard versions 10/10. The operations verifier found both worker metric
series, authenticated dashboard state, NATS lifecycle events, Loki logs and a
Tempo trace spanning worker and shard SGD operations. See the raw
[operations verifier output](evidence/arm64-local-2026-11-02/operations.json)
and [container manifest inventory](evidence/arm64-local-2026-11-02/architecture.json).

An offline checkpoint export and fresh S3 restore through ARM64 SeaweedFS
returned global step 10, shard versions 10/10 and matching hashes for all five
role records. The original one-volume limit failed with `No writable volumes`;
raising `-volume.max` to 2 in `compose.yaml` made the export succeed. See the
[restore manifest](evidence/arm64-local-2026-11-02/s3-restore.json). Keep the
coordinator and shards stopped during offline export because active state stores
hold exclusive locks. The test restored into a temporary directory, not the
retained service volumes.

This is a functional smoke test, not a benchmark or a host sizing result. QEMU
startup was much slower than the ordinary health-check grace period. If A1 is
selected, its native ARM64 performance and sustained memory/disk use with Coolify
remain untested. The selected host's public HTTPS routing, persistence after host
restart and rollback still require checks on an authorized server before deployment
can be called complete. The image was built from the
working tree while ARM64 lock and validation changes were uncommitted; the
evidence records that dirty source state and the exact lock hash.
The isolated test containers were stopped after capture; their named volumes
were retained for local inspection.
