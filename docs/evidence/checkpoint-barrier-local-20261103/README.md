# High-rate synchronous checkpoint barrier — local verification, 2026-11-03

Source under test: `9aada850fabdbffc5077da9a671b2bbf12b2e25e9`.
The test used two worker threads, two independently served parameter-shard
processes, a coordinator process, synchronous mean aggregation, a 30-second
gradient barrier, no training delay and 40 steps. It ran on the local Windows
development host with loopback gRPC; this is multi-process verification, not a
separate-host or WAN result.

## Reproduction and root cause

The reproduction started a checkpoint while a high-rate synchronous shard barrier
was active. Before the fix, the checkpoint remained in `CHECKPOINT_REQUESTED` until
its 20-second export deadline. Both shards had reached the final step, but neither
worker had recorded a checkpoint acknowledgment. The workers had completed their
training loop and sent `completed=true` after the checkpoint began; the completion
path stopped the heartbeat poll and never called `wait_for_checkpoint()`. The
coordinator therefore waited for acknowledgments that could no longer arrive.

The fix adds one final `GetCheckpointControl` read before a worker sends its
completion heartbeat. If the phase is `CHECKPOINT_REQUESTED`, the worker records
the epoch and uses the existing durable acknowledgment and release path. It does
not increase an RPC or barrier timeout, alter gradient semantics, or bypass fencing.

## Repeated measurements

The raw run record is [results.json](results.json). The high-rate regression passed
three consecutive times with measured durations of 6.22s, 6.36s and 6.05s. Each
run produced equal shard versions in the checkpoint manifest, both workers reached
40 steps, and the final shard parameters matched the two-worker uninterrupted SGD
reference within `1e-6`.

The existing local suites also passed after the fix:

- checkpoint epochs: 13 passed in 69.86s;
- shard, failure and worker behavior: 20 passed in 6.00s;
- process recovery: 2 passed in 51.64s;
- checkpoint abort, partial-freeze, uncertain-publication and worker-restart cases:
  5 passed in 22.95s.

These checks cover aborted/failed checkpoint release, restart persistence, duplicate
delivery, synchronous barrier expiry, asynchronous updates and bounded staleness.
The high-rate test also verifies that no gradient is lost or duplicated and that the
published shard versions agree before restore validation.

## Limitation

This closes the deterministic completion race locally. The original two-VM Google
Cloud workload still needs a controlled retest with the fixed source and preserved
traces/logs before the real two-host release gate can be closed. No production VM,
Coolify deployment or second cloud VM was changed for this investigation.
