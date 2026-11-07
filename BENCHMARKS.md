# Correctness evidence and benchmark methodology

The `demo` command is a CPU correctness run, not a performance benchmark.
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
compression gain or cloud performance is claimed. Recovery timings below use a
separate deliberately paced fault scenario.

## Captured process recovery

Clean source `f92103a92071a339253fcad5203642151af650ad`, Windows AMD64,
Python 3.12.10/PyTorch 2.15.0+cpu, November 1, 2026. Two workers/two shards,
20 synchronous steps, 0.1-second deliberate per-step delay. Test leases are
1.5 seconds suspect / 3 seconds unavailable, not the default 5 / 15 seconds.

| Actual terminated process | Detection | Time from termination to later progress | Final shard versions | Raw report |
| --- | --- | --- | --- | --- |
| Worker 0 | 3.000 s heartbeat lease | 7.047 s | 20, 20 | [worker recovery](docs/evidence/worker-recovery.json) |
| Shard 0 | 0.562 s observer RPC failure | 4.828 s | 20, 20 | [shard recovery](docs/evidence/shard-recovery.json) |

Both runs finish with maximum parameter error `5.96e-8` against uninterrupted local
SGD. The worker replacement advances generation 1 to 2 and resumes from durable
step 7. These single-run timings include replacement process startup/imports;
they are not recovery SLAs or steady-state benchmarks. These particular runs did
not replay an in-flight contribution. A separate checkpoint/RPC integration test
forces partial delivery and verifies one replay without duplicate application.
Uncommitted computation lost before journaling is not instrumented.

## Controlled uncompressed framework

```powershell
uv sync --locked --all-extras --python 3.12
.\.venv\Scripts\Activate.ps1
paramesh benchmark --output artifacts/baseline --warmup-steps 20 --steps 200 --repetitions 3
```

Use a fresh output directory: existing results are never overwritten. Each trial
creates separate authenticated coordinator/shard/worker processes and fresh durable
state. Workers finish warm-up, wait until every peer is ready, then begin a measured
session in the same already imported processes. The session includes channel setup,
replacement registration/fencing and final heartbeat. Its throughput is explicitly
**warm-process session throughput**, not pure steady-state compute throughput.
The original startup-inclusive demo duration remains separate.

Modes run sequentially with their order rotated between repetitions. The workload
remains the seeded CPU 4→8→1 MLP and repeated 32-example batch per worker, with one
Torch thread per process, float32 transport, durable SQLite commits and no deliberate
step delay. Bounded mode uses the existing shard-local lag limit of 1; the complete
RunConfig and warm-up session durations are preserved in each raw trial.
Trace/network exporters are disabled; bounded client RPC recording is
enabled consistently across modes. Instrumentation overhead is included and not
calibrated away. This is a small-model protocol/storage-overhead experiment.

| Artifact | Meaning |
| --- | --- |
| `trial-NNN-mode.json` | Complete actual trial, losses, versions, provenance and raw client RPC samples |
| `rpc.csv` | One observed client attempt: method/status, elapsed seconds and protobuf request/response bytes |
| `trials.csv` | Measured window, processed examples, latency percentiles, payload totals, loss and shard-commit deltas |
| `manifest.json` | Configuration, host CPU/RAM/clock, lock hash, actual trial order and completion/failure status |
| `overview.png` / `.svg` | Recorded trial dots, median and observed range; no confidence-interval claim |

Use `--hidden-width 256` to repeat the same seeded workload with a larger MLP and
measure substantially larger raw float32 gradient messages. The default width 8
preserves the original tiny baseline. Width is recorded in the manifest and every
trial; it changes the model computation and payload together, so larger-width
throughput is not a pure transport measurement. Keep correctness/reference checks
enabled and compare actual RPC payload bytes. This loopback benchmark does not model
cross-host bandwidth or establish that compression will help. Large widths can
destabilize this fixed-learning-rate workload; failed numerical checks invalidate
the trial rather than producing performance evidence.

### External workloads

The same benchmark API accepts a `TrainingWorkload` with top-level, spawn-safe
model and batch factories. The bundled CLI remains the deterministic MLP default;
custom workloads can use the runnable example:

```powershell
python examples/external_benchmark.py --output artifacts/external-linear
```

This records the external model, raw RPC observations, mode-specific results,
source metadata and numerical checks in the same artifact schema. Keep the model,
dataset, optimizer and update budget identical when comparing modes; the existing
warnings about different commit semantics still apply.

Completed manifests can be shown in the authenticated dashboard Evidence page by setting
`PARAMESH_EXTERNAL_ARTIFACTS_DIR` to the artifact directory before starting the operations
Compose profile (for example, `python scripts/quickstart.py --no-build`).
Rows are labeled `external workload` and remain read-only post-run evidence; the dashboard does
not claim live monitoring of a separate external process harness.

Each worker records start/end with the same host's system-wide monotonic performance
clock. The aggregate window spans the earliest measured start through the latest
end, excluding result serialization and model evaluation. Processed examples equal
the verified measured worker iterations times batch size; they are not unique data.
Client latency includes the interceptor/application path and server waits, including
synchronous barriers and durable commits. P95 uses the successful observed calls in
each trial; failures remain in the raw CSV and payload totals. Bytes exclude HTTP/2,
TLS and NIC overhead. Captured records contain sizes/statuses, never tensor values
or authentication metadata. Capture overflow fails the benchmark result.

Equal worker iterations cause different SGD commit counts in sync versus async or
bounded mode. Compare convergence and update budgets alongside throughput; do not
turn a mode's rate into a claim of equal-quality training speedup. Three repetitions
describe observed variability and do not establish statistical significance.

The host is an ordinary workstation with background applications and the retained
operations stack running. CPU/memory/clock metadata make that context inspectable,
but do not establish resource isolation or multi-machine network performance.
Completed trial artifacts survive a later failure/interruption; a completed run's
numerical-failure diagnostics are written before validation raises. A mid-trial
termination may yield only failure status, rather than a complete raw result.
Only successful complete output may support a measurement claim. CI's small test runs verify framework behavior,
not a performance baseline. [The design contract](docs/benchmark-design.md) records
the boundaries; [Python clock semantics](https://docs.python.org/3.12/library/time.html)
and [Matplotlib export](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.savefig.html)
support the timing and chart implementation.

## Remaining performance work

### Repeated local fault trials

`paramesh recovery-benchmark --output artifacts/recovery-trials --repetitions 3`
repeats the existing real 20-step synchronous worker-kill and shard-kill scenarios
in fresh processes and durable state. It alternates fault order, retains each raw
JSON run, writes a manifest with hardware/lock/provenance and `trials.csv`, and plots
individual observations with median and observed range. It refuses an existing output
directory and keeps completed reports if a later trial fails. Every recorded success
requires both shards at version 20, completed workers, a positive detection-to-progress
interval and maximum error below `1e-6` against uninterrupted local SGD.

The worker detection observation is the coordinator's 3-second unavailable lease;
the shard observation is a failed 0.5-second RPC probe. They are different detection
mechanisms, so compare each to its own behavior. The run includes a deliberate
0.1-second per-step delay and process replacement/import time. Termination-to-progress
is not full job recovery or an SLA. The harness does not instrument uncommitted
computation lost before journaling; it cannot claim zero lost work. CI's single
repetition checks the CLI and dependencies, not a statistical baseline.

The [recorded local uncompressed baseline](docs/evidence/benchmarks/uncompressed-local-2026-11-02/README.md)
preserves nine clean-source trials, the exact dependency lock, raw RPC observations,
checksums and generated charts. Median warm-process rates were 4,119 / 4,562 / 4,999
processed examples/s for sync / async / bounded respectively. Different update
budgets prevent treating those rates as equal-quality speedups. The 196-byte model
gradient provides no evidence of a network-bandwidth bottleneck, so this dataset
does not justify adding compression.

The operations milestone exposes real protobuf bytes, RPC duration histograms,
worker steps/examples, pre-update loss and accepted staleness. Its deliberately
paced synthetic dashboards are operational evidence, not comparative performance
benchmarks. [The stack report](docs/evidence/operations-stack.json) verifies actual
backend integration at 100 steps; it records its development source identity.
Native worker/shard fault reports above remain the numerical correctness reference.

Broader model/payload sizes, resource isolation, strong/weak scaling, multi-host
network conditions and compression experiments require separate controlled runs.
Compression must be justified by measured payload/bottleneck evidence. Failure
timings require real termination and verified restoration, not simulated statuses.
