# Git-backed Coolify deployment

**Deployed on one Google Cloud Free Trial Linux VM with an authenticated dashboard over HTTPS.**
Coolify manages Docker on the VM. The [hosted run and raw evidence](evidence/gcp-single-host-2026-11-03/README.md)
cover actual native x86-64 training, observability, checkpoint restore and restart.
The [HTTPS rollout evidence](evidence/gcp-hosted-https-2026-11-03/README.md)
records the public route, certificate, authentication and remaining rollback gate.
This is a credit-funded VM, not an Always Free instance or a multi-host deployment.

The deployment path is GitHub → Coolify Application → repository `compose.yaml` →
the same independently running ParamMesh containers tested locally. Keep configuration
changes in Git; do not maintain a pasted, divergent stack in Coolify.

## Target and prerequisites

The first hosted target is a Google Cloud `e2-standard-2` (2 vCPU, 8 GB RAM) VM
in `us-central1-a`, with a 50 GiB `pd-balanced` persistent boot disk. The VM is
x86-64. [Local ARM64 validation](arm64-validation.md) covers emulation only;
native ARM64 remains unverified. The [completed two-host Google Cloud checkpoint evidence](evidence/gcp-multihost-919bc0-20261104/README.md)
verified private-VPC operation, high-rate checkpoint publication, abort/recovery,
raw manifests and numerical agreement. Hosted immutable rollback remains a separate
release gate.
Oracle A1 remains an option if Always Free capacity becomes available.

For any new target, check compute, disk, public IPv4, egress, snapshots and DNS
charges before provisioning. The Google VM consumes promotional credit while it
runs; credits do not make it a $0 ongoing resource. Do not upgrade billing or
assume a second host is covered without checking the available trial balance.

Use a persistent disk and enough memory for five Python/PyTorch processes plus
telemetry and Coolify. The full stack completed on the 8 GB target; available RAM
was about 4.6 GiB after the run, which is an observation rather than capacity sizing.
The build needs access to PyPI, the official PyTorch CPU index and image registries.
Never use the development machine's temporary wheel mirror in a hosted build.

Verify the selected revision locally:

```powershell
python scripts/create_dev_env.py
docker compose build
python scripts/verify_compose.py
python scripts/verify_operations.py --isolated
```

These are local Compose tests, not a substitute for checking Coolify's generated
network/proxy configuration on the real destination.

For a private multi-host Linux layout, see the [multi-host deployment guide](multi-host.md).
Its segmented Docker verification is a local network simulation, not a separate-host
deployment or scaling result.

## Configure the resource

1. In the target Coolify project/environment, choose **New → Public Repository**,
   enter `https://github.com/fetachino/paramesh`, and check the repository.
2. Select `main`, Compose build strategy, base directory `/`, and Compose location
   `/compose.yaml`. Save/reload the parsed definition.
3. Enable **Preserve repository during deployment**: `ops/` contains required
   repository-relative file bind mounts. Use managed Compose deployment, not Raw.
4. Set custom build command `docker compose --profile operations build` and custom
   start command `docker compose --profile operations up -d`. Coolify supplies the
   generated Compose/environment-file flags. The hosted resource uses
   `docker compose --profile operations --profile storage up -d` to include
   private SeaweedFS. Keep the maintenance profile inactive.

These settings follow [Coolify's Git Compose workflow](https://coolify.io/docs/applications/builds/docker-compose).

## Supply environment values

Generate independent strong URL-safe secrets locally with `scripts/create_dev_env.py`
or a trusted password generator. Enter them in the application's environment settings;
do not commit/upload `.env`, put credentials in domains or expose them in screenshots.

| Variable | Value / scope |
| --- | --- |
| `PARAMESH_RPC_TOKEN` | Shared training-group token, 32–256 URL-safe characters |
| `PARAMESH_ADMIN_TOKEN` | Distinct token; coordinator/shards only |
| `PARAMESH_DASHBOARD_PASSWORD` | Distinct operator password; dashboard only |
| `PARAMESH_GRAFANA_PASSWORD` | Distinct operator password; Grafana only |
| `PARAMESH_NATS_TOKEN` | Distinct messaging-group token |
| `PARAMESH_NATS_URL` | `nats://nats:4222` |
| `PARAMESH_OTLP_ENDPOINT` | `http://tempo:4318/v1/traces` |
| `PARAMESH_TRACE_SAMPLE_RATIO` | `0.2` normally; `1` for a short evidence run |
| `PARAMESH_COOKIE_SECURE` | `true` when served over public HTTPS |
| `PARAMESH_STEPS` | Target iteration count, e.g. `1000`; never lower than retained progress |
| `PARAMESH_STEP_DELAY` | `0.05` for a visible demo, `0` for unpaced measurements |
| `PARAMESH_DASHBOARD_PORT` / `PARAMESH_GRAFANA_PORT` | `0` selects random loopback host ports and avoids collisions |

If enabling private SeaweedFS, include `--profile storage` in the start command and
supply distinct `PARAMESH_S3_ACCESS_KEY` / `PARAMESH_S3_SECRET_KEY`. Training roles
do not receive object-storage credentials. S3 export remains an explicit offline
maintenance task, not a startup side effect.

## Route only the dashboard

The hosted resource routes `https://paramesh-operator.duckdns.org` to receiving
service **dashboard**, internal port **8080**, root path, with HTTP redirected to
HTTPS. `PARAMESH_COOKIE_SECURE=true` is set in Coolify. Keep Grafana on loopback
and use an SSH tunnel for private access.
Keep coordinator, shards, workers, NATS, Prometheus, Tempo, Loki and SeaweedFS
without domains. Do not add host gRPC or backend query ports.

Point DNS at the authorized resource server and allow its proxy to receive 80/443.
Coolify's domain port selects the container listener, not a new public host mapping.
The DuckDNS record currently points to the VM's public IPv4 address; update it if
that address changes. The extra `www` route is not configured.
See [domain routing and TLS](https://coolify.io/docs/core/networking/domains) and
[Compose-specific settings](https://coolify.io/docs/applications/configuration/general).

Review the generated definition: only the dashboard should receive public proxy
labels. The proxy must reach its management-side network. Preserve internal training
and operations network isolation; do not expose them to fix a dashboard routing issue.
The default private bridges authenticate RPCs but do not encrypt them. Use the tested
TLS/mTLS options if crossing hosts or an untrusted network.

On the Google VM, the cloud firewall admits only 80/443 publicly and SSH from
the operator's current /32 address. Coolify's UI port 8000 and real-time ports
6001/6002 remain closed publicly. Forward all three together when administering
Coolify through `127.0.0.1`; forwarding 8000 alone produces its “Cannot connect
to real-time service” warning. Use the authorized SSH account, for example:

```text
gcloud compute ssh paramesh-gcp --zone us-central1-a -- -L 8000:127.0.0.1:8000 -L 6001:127.0.0.1:6001 -L 6002:127.0.0.1:6002
```

Dashboard and Grafana use separate loopback host ports assigned by Compose;
inspect their current `docker port` mappings after each deployment and forward
those ports to local `18080` and `13000` if private browser access is needed.
Do not publish either port to the Internet to work around tunnel setup.

## Deploy and verify on the actual server

- Deploy the selected Git revision. Record that revision and inspect build/runtime logs.
- Confirm persistent-role health and dashboard `/healthz`. Workers are finite jobs:
  exit 0 at the target is completion. Inspect how this Coolify version displays them.
- Verify HTTPS, sign-in, Secure cookies, actual advancing state and private Grafana
  access. Cross-site sign-in must remain rejected; preserve the original Host header.
- Confirm metrics, lifecycle history and a cross-service trace using the same
  `scripts/verify_operations.py --project <actual-compose-project>` in the preserved
  checkout. Do not assume Coolify's resource identifier is the Docker project name.
- Inspect host bindings and generated proxy labels; all data-plane/backend ports
  must remain private. Restart roles with retained state and verify their progress.
- Preserve raw verifier reports and checkpoint manifests with their source revision
  and host architecture. Capture screenshots only from actual authenticated views,
  without credentials or account details.

Back up full offline checkpoints outside the server before host maintenance. Named
volumes survive ordinary recreation but are not replicated backups. Never use
`down --volumes` on a retained deployment. Code rollback does not roll model state
back; whole-run restore requires fresh state for every role. See [checkpoints](checkpoints.md).
Coolify currently reports **no saved rollback images** for this resource. Capture
and verify a compatible image rollback before treating that release gate as passed.
The current Compose definition builds the application as the mutable local tag
`paramesh:local`; Coolify's image-retention setting does not turn those build outputs
into a selectable rollback when no registry image or prior Coolify image record is
available. The VM retains the live image and two older `mh-*` images from the
multi-host trial, but those tags are not Coolify deployment records. See the
[rollback evidence](evidence/gcp-hosted-rollback-2026-11-03/README.md).

For a safe rollback, first export the current image by digest and all named volumes,
record the source revision and Compose configuration, and verify the archive hashes.
Validate the candidate image in an isolated network-disabled container and check its
CLI/configuration compatibility. Only then deploy the candidate by immutable digest
with the same environment and retained volumes. Never use `down --volumes`, restore
one shard without its peers, or mix a checkpoint from one code/topology generation
with another. Restore into fresh volumes if the live state is incompatible; keep the
original volumes untouched until the replacement passes health, authentication,
HTTPS, retained-step and telemetry checks.

OpenTofu and k3s are deferred until an actual host/provisioning requirement exists;
placeholder infrastructure cannot establish a working public deployment.
