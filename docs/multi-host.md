# Multi-host Linux deployment path

**Deployment configuration prepared and locally exercised; separate-host operation is not yet validated.**

`deploy/multihost/compose.yaml` overlays the existing Compose stack. It publishes
only the ports needed between private Linux hosts, binds them to a configured
private interface, disables same-project worker dependencies, mounts the shared
run config and per-host certificates, and keeps each role's existing named state
volume local to its Docker host. The overlay adds a `host-link` bridge to roles
that need private VPC traffic; the original internal training/operations networks
remain in place. Cloud firewall rules must restrict the published private-IP
ports to the participating hosts. Use private DNS names or stable private IPs in
the run config and `.env`; Compose service names only resolve within a Compose
network. Docker documents that service-name discovery is scoped to shared Compose
networks and that host port mappings are needed for communication outside them
([Compose networking](https://docs.docker.com/compose/how-tos/networking/),
[Compose port mappings](https://docs.docker.com/reference/compose-file/services/#ports)).

The repository has **not** run on multiple Linux hosts. The local check uses
separate containers with fixed private IPs on one isolated Docker Desktop Linux
engine. It verifies direct addressing, TLS, training, monitoring and restart
behavior without modeling host firewalls, separate kernels, WAN latency or a real
cloud network.

## Network layout

Place any combination of these roles on separate hosts. The operations services
can remain together on a management host; coordinator, shards and workers use
private DNS names that resolve from every participating host.

| Traffic | Default host port | Allowed source |
| --- | ---: | --- |
| Coordinator gRPC | `50050` | Worker and dashboard hosts |
| Shard gRPC | `50051` | Coordinator and worker hosts |
| NATS lifecycle events | `4222` | ParamMesh hosts and dashboard host |
| Tempo OTLP/HTTP traces | `4318` | ParamMesh hosts |
| Prometheus scrape targets | `9101`–`9106` | Operations host only |
| Dashboard | `8080` | Local Coolify proxy only |
| Prometheus, Grafana, Loki, Tempo query, NATS monitoring | internal | Operations host only |

The overlay binds published gRPC, NATS, OTLP and metrics ports to
`PARAMESH_PRIVATE_BIND_IP`. Restrict those ports to the listed private source
hosts in the VM/cloud firewall and Linux firewall. Keep the dashboard on its
existing loopback host mapping for the Coolify proxy; do not publish Grafana,
Prometheus, Loki or backend query ports. Assign distinct published ports if
multiple copies of one role share a host, then use those same host ports in the
run config and Prometheus target files.

## Per-host configuration

Build and run the same Git revision on each Linux host. Copy the same run config
to every ParamMesh host; its `shard_endpoints` must name the private host address
and published port for each shard. Set `PARAMESH_RUN_ID` to its `run_id`.
Do not commit `.env`, certificates, private keys, or the populated Prometheus
target directory.

Use Docker Compose 2.24.4 or newer; the overlay uses Compose's `!reset` merge tag
to remove local worker dependencies and local-only published ports
([Compose merge rules](https://docs.docker.com/reference/compose-file/merge/)).

Set the following values in a host-local `.env` file:

| Variable | Purpose |
| --- | --- |
| `PARAMESH_PRIVATE_BIND_IP` | This host's private interface address for published ports |
| `PARAMESH_CONFIG_FILE` | Absolute path to the shared run JSON file |
| `PARAMESH_RUN_ID` | Exact `run_id` from that JSON file; used by shard health checks |
| `PARAMESH_TLS_DIR` | Directory containing `ca.pem`, `rpc.crt`, `rpc.key` |
| `PARAMESH_COORDINATOR_ENDPOINT` | Private coordinator DNS/IP and published gRPC port; needed by workers and dashboard |
| `PARAMESH_RPC_TOKEN` | Shared data-plane credential for coordinator and shards |
| `PARAMESH_ADMIN_TOKEN` | Distinct admin credential; only required on coordinator and shard hosts |
| `PARAMESH_NATS_URL` | For example, `tls://nats.private.example:4222`; leave empty only if events are disabled |
| `PARAMESH_NATS_TOKEN` | Shared NATS token for publishers and dashboard subscriber |
| `PARAMESH_OTLP_ENDPOINT` | For example, `http://tempo.private.example:4318/v1/traces` |
| `PARAMESH_NATS_TLS_DIR` | On the NATS host only, directory containing `nats.crt` and `nats.key` |
| `PARAMESH_PROMETHEUS_TARGETS_DIR` | On the operations host, directory containing populated target JSON files |

Each `rpc.crt` must be signed by the CA in `ca.pem`, include the host's DNS name
and private IP in its SANs, and be usable for server and client authentication.
Include `localhost` and `127.0.0.1` for the existing in-container health probes.
Use a separate NATS server certificate and key in `PARAMESH_NATS_TLS_DIR`; only
the NATS container mounts that directory. NATS clients trust `ca.pem` and use the
token after the TLS connection is established. ParamMesh gRPC requires mTLS and
still applies its separate data/admin tokens. These settings use the project's
existing gRPC TLS support ([gRPC authentication](https://grpc.io/docs/guides/auth/))
and the official NATS server/Python client TLS configuration
([NATS TLS](https://docs.nats.io/learn/security/encryption),
[nats.py TLS client](https://github.com/nats-io/nats.py#tls)).

Prometheus reads `file_sd` targets from `PARAMESH_PROMETHEUS_TARGETS_DIR`; the
checked-in files under `deploy/multihost/prometheus-targets/` are placeholders.
Copy that directory on the operations host, replace the example names and ports
with the private host addresses, then set the variable. Prometheus refreshes those
files every 15 seconds ([file-based service discovery](https://prometheus.io/docs/guides/file-sd/)).
Workers are finite jobs, so their scrape targets go down after successful
completion; their samples remain in the local Prometheus volume.

OTLP/HTTP and Prometheus scraping are plain HTTP in this profile. Keep them on a
trusted private network or VPN and firewall them to the expected peers. NATS and
ParamMesh gRPC traffic use TLS; metrics and trace transport do not.

## Start selected roles

Run from the repository root on each host. `-p paramesh` gives state volumes a
stable name across container recreation; Docker hosts keep their volumes
independent.

```sh
docker compose -p paramesh -f compose.yaml -f deploy/multihost/compose.yaml config --quiet
docker compose -p paramesh -f compose.yaml -f deploy/multihost/compose.yaml up --build -d coordinator
```

Start the matching shard service on its host with `shard-0` or `shard-1`; start
`worker-0` and/or `worker-1` on worker hosts. The overlay removes Compose's local
`depends_on` startup chain for workers; each worker connects to
`PARAMESH_COORDINATOR_ENDPOINT` and receives the shard endpoints from the
coordinator's run config. On the operations host, start the private backends and
dashboard with:

```sh
docker compose -p paramesh -f compose.yaml -f deploy/multihost/compose.yaml --profile operations up --build -d dashboard nats prometheus tempo loki grafana
```

Only the existing dashboard reverse-proxy route should be public. Use an SSH
tunnel for Grafana administration. The remote `PARAMESH_NATS_URL` must use
`tls://`; the overlay configures the NATS server listener with its certificate.

## State, restarts and backups

Coordinator, each shard, each worker, and the operations services keep state in
their existing named volumes on their own hosts. Do not mount one SQLite state
directory over multiple hosts or expect Docker volumes to replicate themselves.
Coordinator and shard containers restart with their local durable state. Workers
resume from their local journal after a failed process restart; a worker that
already exited successfully at its finite step target does not restart itself.
To extend the run, recreate the worker with a target at least as large as its
retained progress.

Export coordinated checkpoints before host maintenance and store the immutable
checkpoint outside the host being protected. Local volume persistence is not a
backup or live replica. Follow [checkpoint operations](checkpoints.md) for export,
restore and the limits of current recovery semantics.

## Local verification and limits

Run the same-host private-network simulation with:

```sh
uv run python scripts/verify_operations.py --multihost-simulation --output artifacts/multihost-simulation.json
```

The script builds the current image, creates temporary CA and host certificates,
starts an isolated bridge with fixed role IPs, trains 100 steps with mTLS, verifies
NATS TLS/token event delivery, Prometheus scrapes, Loki lifecycle records, a
worker-to-shard Tempo trace, and retained coordinator/shard progress after restart.
It removes only its unique Compose project and generated certificates. The checked
run passed with global step 100, shard versions `[100, 100]`, four healthy persistent
scrapes, and retained state after coordinator/shard restart. Its preserved report is
[`verification.json`](evidence/multihost-local-simulation-2026-11-02/verification.json).

This validates address/configuration wiring over a private container bridge. It
does not validate separate Linux hosts, host firewalls, DNS management, WAN
performance, provider capacity, or public deployment. Controlled multi-host
measurements and hosted HTTPS remain open.
