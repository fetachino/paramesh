# Visual evidence

Captured November 1, 2026 from real local Compose services in a browser. The dashboard
uses synthetic CPU regression data. Source was the operations development tree after
`f313d874`; these screenshots do not claim a clean-release capture or hosted deployment.
IAB viewport was 1280px wide; full-page captures retain the visible page contents.
Only the topology panel is cropped for a focused architecture view.

| Image | Actual evidence |
| --- | --- |
| `cluster-overview.png` | Advancing synchronous run, real scraped loss/throughput and leases |
| `distributed-training.png` | Real worker progress and authoritative shard versions |
| `cluster-topology.png` | Five training roles after 2,000 completed synchronous steps |
| `bounded-staleness.png` | Separate fresh project, lag bound 2, 1,000 worker iterations / 2,000 shard commits |
| `worker-recovery.png` | Actual killed-worker loss/rejoin events; native measured correctness reports labeled separately |
| `checkpoint-restore.png` | Actual 2,000-step publication event plus a clearly labeled recorded fresh-volume/S3 restore check |
| `benchmark-dashboard.png` | Historical correctness/failure reports with source and unequal update semantics stated |
| `grafana-overview.png` | Provisioned dashboard showing real Prometheus series, including the outage |
| `distributed-trace.png` | Actual sampled Tempo worker/RPC/shard-commit waterfall |
| `github-actions.png` | Genuine successful recovery-milestone Actions quality/container jobs |

Browser QA exercised Chrome at 320, 768, 1024 and 1440px without document overflow;
the temporary override was reset. Sign-in, navigation, trace loading, empty states,
session reset after restart and console errors were checked. The in-app browser's
viewport override did not change its measured size; responsive claims rely on Chrome.
No `coolify-deployment.png` exists because a public deployment has not happened.

These are operational/correctness observations. Deliberate step pacing, startup,
polling and unrelated local work make them unsuitable for throughput comparisons.
