# Controlled uncompressed benchmark contract

Reuse the existing independent-process harness, workload, authentication and durable
state. Do not change SGD, recovery, production worker interfaces or the retained
Compose deployment to obtain a benchmark.

Each trial owns fresh state. Workers complete a warm-up session, report readiness,
then await a parent-issued measurement command. The measured session runs in those
already imported processes against the same durable weights/journals. It includes
channel setup, replacement registration/fencing and final heartbeat; report that
boundary explicitly rather than claiming pure steady-state compute throughput.
Keep the existing startup-inclusive correctness duration separately.

Capture bounded client RPC observations through the existing telemetry interceptor:
method, status, elapsed time and protobuf request/response sizes only. No credentials,
tensors or arbitrary metadata enter the records. Overflow fails the benchmark claim;
it must not silently truncate a timing distribution. Ordinary services do not retain
raw samples. Existing numerical/reference checks must still pass.

Run sync/async/bounded modes sequentially, rotate their order between repetitions,
and preserve trial JSON immediately. Export raw RPC CSV, per-trial CSV, configuration,
dependency-lock hash, revision/dirty status, CPU/RAM/platform and clock metadata.
Produce standalone charts from recorded values; show repeats and unequal SGD-update
semantics. The fixed tiny CPU model is an instrumented overhead baseline, not a
multi-machine scaling or network-bandwidth benchmark. Background workstation load
remains a stated limitation; do not stop the retained operations stack.

Acceptance: controlled warm-up exclusion, exact measured example counts, real RPC
sizes/statuses, synchronous reference error below 1e-6, bounded sample storage, raw
artifact/chart consistency, and unchanged correctness/fault/Compose checks. Use
three repetitions initially; no fabricated speedups or compression justification.
The benchmark's optional `--hidden-width` retains the same data, process topology,
optimizer and telemetry while increasing model and gradient size. Since compute
also grows with width, report it as a larger-payload loopback experiment, not an
isolated transport or multi-host network test.
The fixed learning rate can make very wide models numerically unstable; the harness
keeps the reference/error gate and rejects such trials instead of recording rates.

The separate `recovery-benchmark` command reuses the actual process-kill demo, not
synthetic status injection. Its deliberately paced scenario measures detection and
time until later worker progress; it validates the final full-run numerical result
for every trial. Keep its time boundaries distinct from throughput measurements.
