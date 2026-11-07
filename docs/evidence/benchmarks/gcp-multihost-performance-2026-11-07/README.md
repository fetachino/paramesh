# Google Cloud multi-host performance evidence (2026-11-07)

This directory records a controlled, isolated two-host synchronous workload. It is
evidence of one measured topology, not a general scaling claim.

## Identity and isolation

- Source used for the disposable run: ParamMesh v1.0.0 immutable image,
  `ghcr.io/fetachino/paramesh@sha256:8704ead5088d3adb03641ea6a7ce30bcdd6474311df4d9cc7f2545570ad317b3`.
- The image's OCI source revision is the v1.0.0 release revision; it is not the
  current `main` revision and is recorded here to keep the measurement reproducible.
- Primary host: existing `e2-standard-2` VM in `us-central1-a`, private address
  `10.90.0.2`. Only a separate Compose project was used; the Coolify production
  project, volumes, credentials, and HTTPS route were not changed.
- Temporary secondary host: disposable `e2-standard-2` VM in the same private VPC,
  private address `10.90.0.8`. It and its temporary private firewall rule were
  deleted after evidence collection.
- Raw logs and environment files (including credentials and TLS keys) remain outside
  Git under `D:\ParamMesh-private\mh-perf-20261107`.

## Workload

Two workers, two authoritative shards, synchronous barriers, 200 steps, float32
CPU execution, SGD learning rate `0.05`, no compression, and a 30-second barrier
deadline. The same workload was run twice after setup was corrected. Both clean
trials reached global step 200 with both shard versions at 200 and both workers
exiting with code 0.

| Trial | Worker wall time (s) | Shard versions | Result |
| --- | ---: | --- | --- |
| Same-host Linux baseline | 26.4208886 (max worker) | 200, 200 | completed |
| Two-host run 2 | 73.1217060 (max worker) | 200, 200 | completed |
| Two-host run 3 | 98.0956231 (max worker) | 200, 200 | completed |

The two-host measurements are approximately 2.77x and 3.71x the same-host
baseline for these individual trials. This is an observed comparison, not a
scaling law: only two clean repetitions, one VM size, one workload, and one
private-region placement were measured. The first setup trial had transient
firewall/token configuration errors and is retained as operational evidence, but
is excluded from the performance summary.

A separate Windows local reference for the same 200-step workload completed in
6.5497551 seconds with shard versions `[200, 200]` and maximum parameter error
`3.57627868652344e-07`; it is not a cross-host performance comparison.

## Boundaries

This evidence does not validate WAN or multi-region behavior, compression, GPU
execution, coordinator high availability, four/eight-host scaling, or arbitrary
PyTorch models. The checkpoint correctness and recovery release gate is covered by
the earlier two-host evidence; this directory adds a narrow performance baseline.
The raw private logs, command transcripts, and source/configuration metadata are
available for an operator review without placing secrets in the public repository.
