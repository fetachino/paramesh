# External linear workload repeatability

This is a three-repetition Windows AMD64 clean-room run of the external
`torch.nn.Linear(4, 1)` workload. It was executed from a fresh user clone with
Python 3.12, 20 warm-up steps, 200 measured steps, two workers and two shards.
The source tree was clean at commit `5a09326572d02402eaf01f108ec6a4af32472fde`.

All 9 trials completed with zero RPC failures. Observed examples/second ranges
and medians were:

| Mode | Range | Median |
| --- | ---: | ---: |
| sync | 2,603.5–5,513.0 | 3,440.8 |
| async | 3,563.0–5,650.8 | 3,782.8 |
| bounded | 3,520.9–5,706.5 | 5,404.7 |

The synchronous trials had zero reference parameter error and all modes reached
their expected shard commit deltas. The host had uncontrolled background load;
these measurements establish repeatable smoke behavior, not statistical
performance superiority or external-user adoption.

`manifest.json`, `trial-*.json`, `rpc.csv`, and `trials.csv` are the raw
sanitized artifacts. `overview.png` and `overview.svg` are generated charts.
