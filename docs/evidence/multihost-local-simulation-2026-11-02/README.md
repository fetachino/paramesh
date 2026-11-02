# Multi-host path local simulation

This is a segmented-network readiness check on one Docker Desktop Linux AMD64
engine. It is **not** a run on separate Linux hosts and does not provide a
multi-host performance result.

Run from the repository root:

```sh
uv run python scripts/verify_operations.py --multihost-simulation --output artifacts/multihost-simulation.json
```

The verifier builds the application image, checks the production Compose overlay,
creates temporary role certificates and credentials, and starts an isolated set
of services with direct private IP endpoints on internal Docker networks. It
checks synchronous training, RPC mTLS, NATS TLS and token authentication,
Prometheus remote-IP scrapes, Loki event records, a worker-to-shard Tempo trace,
and coordinator/shard persistence after restart. It then removes only its
uniquely named Compose project, volumes, and temporary credentials.

The preserved `verification.json` records the source revision, local Docker
platform, private addresses, scrape results, trace, state before/after restart,
and the explicit `separate_hosts: false` limit. This verifies configuration and
addressing paths while leaving separate-host DNS, firewall, kernel, WAN and
provider behavior open.
