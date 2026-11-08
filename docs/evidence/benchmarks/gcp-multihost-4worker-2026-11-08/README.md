# Google Cloud four-worker multi-host evidence (2026-11-08)

This record documents one clean, isolated four-worker synchronous run across
two Google Cloud Linux VMs. It extends the supported experimental topology; it
is not a broad scaling claim or a production deployment.

## Reproducibility

- Source: `ed5809e27352ffc5623fe3ea93dbe148a97d3e5d`
- Image: `ghcr.io/fetachino/paramesh@sha256:8704ead5088d3adb03641ea6a7ce30bcdd6474311df4d9cc7f2545570ad317b3`
- Platform: Linux amd64, two temporary `e2-standard-2` VMs, private VPC
- Primary host: `10.90.0.2` (coordinator, shard-0, workers 0/1)
- Secondary host: `10.90.0.9` (shard-1, workers 2/3)
- Workload: synchronous float32 CPU SGD, two shards, four workers, 100 steps,
  learning rate `0.05`, barrier deadline 30 seconds, no compression
- The production Coolify project, volumes, credentials, HTTPS route and
  application containers were not changed.

The temporary secondary VM and its two private firewall rules were deleted after
the run. Raw logs, state snapshots, VM metadata and checksums remain outside Git
under the operator's protected evidence directory; no credentials or private
keys are included here.

## Results

| Check | Observed result |
| --- | --- |
| Workers 0–3 | Each completed step 100 and exited with code 0 |
| Coordinator | Healthy; all four workers recorded at step/version 100 |
| Shard versions | shard-0 = 100, shard-1 = 100 |
| Shard receipts | Four receipts on each shard |
| State consistency | Both shard snapshots had matching run/config state and `checkpoint_epoch=0` |
| NATS | Healthy after isolated TLS/token setup |
| Production after cleanup | Existing production services remained healthy |

See [`results.json`](results.json) and [`trials.csv`](trials.csv) for the
sanitized machine-readable record. The worker loss curves are retained in the
protected raw logs rather than committed because they are diagnostic output,
not a benchmark matrix.

## Interpretation and limits

This run demonstrates that the checked-in four-worker overlay can complete a
real private-VPC workload with equal shard versions and durable state on two
separate kernels. It does not establish throughput scaling, WAN behavior,
multi-region behavior, compression need, coordinator high availability, GPU
support, or arbitrary worker counts. Repeated performance trials and controlled
fault-timing measurements remain separate work.
