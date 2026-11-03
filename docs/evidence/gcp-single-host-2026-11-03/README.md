# Google Cloud single-host Coolify verification

Captured on November 3, 2026 UTC from a real Google Cloud Compute Engine Linux
VM, not a local Docker simulation. Coolify built and ran repository `main` at
`65292da8460a4cc0d91f2fd45dd4e43f1cf20178`. Its deployment finished
successfully. The host is `e2-standard-2` (2 vCPU, 8 GB RAM), 50 GiB
`pd-balanced` persistent boot disk, `us-central1-a`, `linux/x86_64`. This is one
credit-funded Free Trial VM; it does not verify multi-host scaling or native ARM64.

The application used the repository's Compose stack with `operations` and
`storage` profiles. The coordinator, two shards, dashboard, NATS, SeaweedFS,
Prometheus, Grafana, Loki and Tempo ran on the VM. Two workers completed 1,000
synchronous steps and exited 0. The source/image identity, `global_step=1000`,
both shard versions at 1,000, authenticated dashboard, Prometheus scrapes,
Loki lifecycle records and an eight-span worker/shard trace are in the
[first raw verifier report](gcp-operations.json).

An offline whole-run local checkpoint was published to a retained Docker volume
at step 1,000, with all five role records and shard versions `[1000,1000]`.
Its [raw manifest](gcp-checkpoint-manifest.json) is preserved. A disposable
helper restored that checkpoint into a fresh directory. Authenticated
S3-compatible export to the host's SeaweedFS also published and restored at
step 1,000; its [raw restore record](gcp-s3-restore.json) is preserved.
These are host-local and S3-compatible checks, not a managed AWS/Azure backup.

The coordinator, shards and workers were restarted with the named volumes
retained. Both workers exited 0 again without advancing past the completed
target. The [post-restart verifier report](gcp-operations-after-restart.json)
again records step 1,000, versions `[1000,1000]`, authenticated dashboard,
healthy Prometheus scrapes, Loki records and a worker/shard trace.

The Google firewall admits SSH only from the operator's /32 address and public
80/443 for future proxy routing. Coolify 8000/6001/6002, dashboard, Grafana
and backend ports are not publicly admitted; Coolify, dashboard and Grafana
were reached through SSH loopback tunnels. Forwarding 6001/6002 resolved the
Coolify real-time warning without opening those ports to the Internet.
Grafana's authenticated API reported Prometheus, Loki and Tempo data sources
and the ParamMesh training operations dashboard. No controlled domain has
been configured, so public HTTPS and secure-cookie behavior are not claimed.

The JSON files contain no service credentials. They are correctness and
operations evidence, not a throughput benchmark. Later polling after all
workers completed found no *recent* trace; the two time-stamped successful
reports above captured cross-service traces while the run was active.
Code rollback, off-host backup durability, WAN access and a second host remain
unverified.

At capture time, the Google Cloud Billing Overview showed **Free Trial**,
`$300` credit out of `$300`, and 45 days remaining, ending December 18, 2026.
The cost view still covered November 1–2 and warned that usage can take more
than 24 hours to appear; its `$0.00` was not evidence that this VM is free.
Using Google's listed Iowa on-demand rates, the running VM, 50 GiB balanced
disk and one external IPv4 are approximately **$0.079/hour** or **$58 for
730 hours**, before egress, logs, snapshots, taxes or other usage. Rates:
[compute](https://cloud.google.com/products/compute/pricing/general-purpose),
[disk](https://cloud.google.com/compute/disks-image-pricing),
[IPv4](https://cloud.google.com/vpc/network-pricing). The trial balance and
actual billed usage must be checked again before any further resource creation.
