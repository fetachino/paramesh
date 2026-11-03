# Hosted dashboard HTTPS rollout — 2026-11-03 UTC

This records a real deployment on the existing Google Cloud `paramesh-gcp`
`e2-standard-2` x86-64 VM in `us-central1-a`, running source revision
`a3486e33e26eee150406827b9f713bebd289f519`. This is one host, not a
multi-host or native ARM64 result. The existing named volumes, retained training
state, credentials and VM were preserved.

## Build diagnosis and recovery

Coolify deployment `8vecscvl3uzm1sutilms29tv` started at 20:28:14 UTC and
reported success around 20:53 UTC. After its last build log at 20:32:57, the
Buildx/docker-compose helper processes remained running (`Sl`). Host checks found
CPU pressure `some avg10` around 93–98% and load as high as 32 on 2 vCPUs.
Memory had about 4.7 GiB available out of 7.7 GiB, with no swap. The 48 GiB boot
filesystem had 26 GiB free (47% used). Docker had no recent warning journal
entries. Docker image create/tag events around 20:48:07 showed build progress;
Coolify resumed logging at 20:48:33. This supports resource contention, not a
confirmed Buildx deadlock. No second build or application source change was made.

The rollout recreated application containers without removing named volumes. The
dashboard first failed a 3-second health probe under load, then returned `/healthz`
200 in 0.33 seconds and became healthy. Finite workers reached the retained
1,000-step target and exited normally. An authenticated `/api/state` probe after
deployment returned coordinator status, both shard steps at `1000`, and
Prometheus, Loki and Tempo reachable.

## Public route and access checks

| Check | Observed result |
| --- | --- |
| DuckDNS A lookup | `paramesh-operator.duckdns.org` → `35.206.82.179`; Coolify DNS check matched |
| HTTP | `307` redirect to HTTPS |
| HTTPS `/` | `303` redirect to `/login` without a session |
| HTTPS `/healthz` | `200` |
| HTTPS `/api/state` without a session | `401` |
| TLS | Trusted Let's Encrypt certificate for the hostname, TLS 1.3, expires 2027-02-01 UTC |
| Login | `operator` login returned a session cookie with `Secure`, `HttpOnly` and `SameSite=Strict`; authenticated `/api/state` returned `200` |

Checks used the browser's normal certificate validation, PowerShell HTTP requests,
and Python's default trusted TLS context. No credentials or session values are
stored here. The dashboard login page also loaded in Chrome over the public
hostname without a certificate warning.

The dashboard alone has a Traefik HTTPS router label, with internal port 8080.
Grafana is bound to `127.0.0.1` on the host; coordinator, shards, workers, NATS,
Prometheus, Loki, Tempo and SeaweedFS have no public proxy route or public host
binding. The VM's custom VPC firewall admits public 80/443 and operator `/32` SSH;
Coolify administration ports 8000/6001/6002 stay private. This verifies the
configured routing boundary, not an external penetration test.

## Remaining gates

Coolify's Rollback panel reported **no saved rollback images** at the end of this
rollout. A compatible hosted image rollback and state persistence after it have
not been tested. The separate high-rate synchronous checkpoint barrier failure
also remains unresolved. Neither a `v1.0.0` release nor a controlled scaling
benchmark result follows from this HTTPS deployment.
