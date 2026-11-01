# Correctness evidence and benchmark methodology

The current harness is a CPU correctness demo, not a performance benchmark.
It runs real training in independent processes and exports a JSON report:

```powershell
paramesh demo --mode sync --workers 2 --shards 2 --steps 20 --output artifacts/sync.json
paramesh demo --mode async --workers 2 --shards 2 --steps 20 --output artifacts/async.json
paramesh demo --mode bounded --workers 2 --shards 2 --steps 20 --output artifacts/bounded.json
```

## Numerical reference

### Captured CPU evidence

These are actual 20-step runs at commit
`fca471cdfaa0e12bd8dcf212323b7013685e895d` with a clean working tree, recorded
on November 1, 2026 using Windows AMD64, Python 3.12.10 and PyTorch 2.15.0+cpu.
Each run used two workers and two nonempty shards; both workers completed.

| Mode | Initial MSE | Final MSE | Final shard versions | Max absolute error vs local SGD | Raw artifact |
| --- | --- | --- | --- | --- | --- |
| Sync | 14.232687 | 0.733824 | 20, 20 | 5.96e-8 | [JSON](docs/evidence/sync-cpu.json) |
| Async | 14.232687 | 0.538783 | 40, 40 | Not equivalent | [JSON](docs/evidence/async-cpu.json) |
| Bounded | 14.232687 | 0.508454 | 40, 40 | Not equivalent | [JSON](docs/evidence/bounded-cpu.json) |

These final losses are single-run observations, not a convergence ranking. Async
and bounded runs have twice as many shard SGD updates as sync for the same local
worker iteration count. Their artifacts were collected concurrently, so wall
times must not be used for a performance comparison. No CPU/RAM inventory or
steady-state benchmark was collected for these correctness runs.

The sync reference uses the same seeded MLP initialization, concatenates the same
32-example worker datasets and applies PyTorch SGD for the same number of steps.
Worker mean-reduced MSE gradients are averaged by each shard. Since worker batches
are equal-sized, that matches the reference objective. Tests require maximum
absolute parameter difference below `1e-6` and loss reduction.

Async and bounded runs assert completion, expected shard update counts and loss
reduction for this workload. They are not compared numerically to sync because
their update order and model snapshots differ. This is not a general convergence
guarantee for arbitrary models or learning rates.

## Report fields and limitations

Reports include worker/shard counts, process count, version counters, ownership,
initial/final full-dataset loss, worker-local pre-update losses, refresh counts,
reference error, Python/PyTorch/OS/architecture, timestamp and Git commit/dirty state.
The workload description records model dimensions, seeds, batch size, learning
rate, optimizer, aggregation, CPU device and thread count. Unknown Git provenance
is labeled `unknown`, such as when using a wheel outside a checkout.

`worker_wall_seconds_including_startup` begins before workers are spawned and ends
when their results arrive. It includes imports, startup, training and final heartbeat;
it excludes shard/coordinator startup, cleanup and the local reference. It is not
steady-state throughput or an RPC latency metric. No speedup, scaling efficiency,
recovery time, compression gain or cloud performance is claimed.

## Future performance work

Use fixed datasets and controlled model sizes, distinguish strong from weak
scaling, separate startup from steady-state measurement, warm up, repeat runs and
report distributions. Record CPU/RAM and dependency versions, configuration, source
identity, worker/shard topology, examples processed, bytes and per-RPC latency.
Compare sync/async/bounded modes with convergence as well as throughput. Persist
raw JSON/CSV before generating charts. Failure timings require real process
termination and verified restoration, not simulated status values.
