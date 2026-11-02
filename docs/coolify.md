# Git-backed Coolify deployment

**Prepared and tested locally; public deployment is pending an available server.**
No Coolify resource, public hostname or hosted success screenshot exists yet.
Coolify manages Docker on a server; it does not supply free compute. Do not create
a paid server, subscription, domain purchase or cloud storage account for this demo.

The deployment path is GitHub → Coolify Application → repository `compose.yaml` →
the same independently running ParamMesh containers tested locally. Keep configuration
changes in Git; do not maintain a pasted, divergent stack in Coolify.

## Before deployment

The hosted Linux target remains flexible: Oracle Cloud Always Free Ampere A1 if
capacity returns, an Azure VM if the student subscription is approved and the VM
fits its no-charge allowance, or another genuinely free Linux VM. No provider has
been selected and no cloud resource has been created. [Local ARM64 validation](arm64-validation.md)
covers the image and Compose stack under emulation; it does not establish a native
host, provider quota, or Coolify deployment.
Use a persistent disk and enough memory for five Python/PyTorch processes plus
telemetry and Coolify. Establish actual host limits before a sizing claim.
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
   generated Compose/environment-file flags. Keep the maintenance profile inactive.

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

Add an HTTPS domain for receiving service **dashboard**, internal port **8080**,
root path. Keep Grafana, coordinator, shards, workers, NATS, Prometheus, Tempo, Loki
and SeaweedFS without domains. Keep host mappings on loopback; use an SSH tunnel
for private Grafana administration. Do not add host gRPC or backend query ports.

Point DNS at the authorized resource server and allow its proxy to receive 80/443.
Coolify's domain port selects the container listener, not a new public host mapping.
See [domain routing and TLS](https://coolify.io/docs/core/networking/domains) and
[Compose-specific settings](https://coolify.io/docs/applications/configuration/general).

Review the generated definition: only the dashboard should receive public proxy
labels. The proxy must reach its management-side network. Preserve internal training
and operations network isolation; do not expose them to fix a dashboard routing issue.
The default private bridges authenticate RPCs but do not encrypt them. Use the tested
TLS/mTLS options if crossing hosts or an untrusted network.

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
- Capture `docs/images/coolify-deployment.png` only after these checks succeed,
  with server addresses, account details and credentials excluded.

Back up full offline checkpoints outside the server before host maintenance. Named
volumes survive ordinary recreation but are not replicated backups. Never use
`down --volumes` on a retained deployment. Code rollback does not roll model state
back; whole-run restore requires fresh state for every role. See [checkpoints](checkpoints.md).

OpenTofu and k3s are deferred until an actual host/provisioning requirement exists;
placeholder infrastructure cannot establish a working public deployment.
