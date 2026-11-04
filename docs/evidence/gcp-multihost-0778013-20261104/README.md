# Google Cloud two-host checkpoint retest (2026-11-04)

This directory records a controlled, isolated two-host Google Cloud run using
main revision `077801304c6dbf1f1a28c029871f13f5990f43df`, which contains the
PR #31 checkpoint completion race fix and the squash-merged PR #33 worker
recovery fix.

## Scope

- Primary production VM: `paramesh-gcp` (`e2-standard-2`, `10.90.0.2`), used
  only for an isolated Compose project named `paramesh-mh-fixed`.
- Temporary secondary VM: `paramesh-mh-test-20261104` (`e2-standard-2`,
  `10.90.0.6`, Ubuntu 24.04 amd64).
- Temporary private firewall: `paramesh-mh-private-20261104`, limited to the
  private VPC CIDR and internal RPC/observability ports.
- No Coolify production services, credentials, named volumes, checkpoints, or
  HTTPS routes were changed.

## Observed results

The uninterrupted high-rate run completed three live checkpoints while both
workers were active. Every checkpoint reported equal shard versions:

| checkpoint | global step | shard versions | duration (s) |
| --- | ---: | --- | ---: |
| `highrate-1` | 236 | `[236, 236]` | 99.23 |
| `highrate-2` | 530 | `[530, 530]` | 81.30 |
| `highrate-3` | 954 | `[954, 954]` | 62.56 |

Worker-0 was terminated and restarted after the third checkpoint. It resumed
from durable progress (`resumed_from: 1264`, `replayed_contributions: 2`) and
completed the configured 2,000-step workload with exit code 0. No duplicate
commit or journal-loss error was observed.

A separate isolated run exercised a failed live checkpoint. Freeze correctly
failed with `Cannot freeze a shard with pending synchronous contributions`,
then `live-abort --id abort-check` completed successfully. Both workers later
completed their 2,000-step workloads and exited cleanly.

## Release-gate status

**The real two-host checkpoint release gate remains open.** The run proves
cross-host high-rate checkpoint completion, equal versions, worker restart
recovery, and checkpoint abort handling. It does not close the gate because:

1. the isolated checkpoint volume was intentionally reset between runs, so the
   raw manifest bundle for `highrate-1` through `highrate-3` was not retained;
2. a successful checkpoint after the abort was not captured; and
3. a direct numerical comparison against an uninterrupted reference artifact
   was not collected on the real hosts.

These are evidence gaps, not claims of protocol failure. No timeout was
increased to obtain the results.

See `results.json` and the sanitized logs for the reproducibility record.
