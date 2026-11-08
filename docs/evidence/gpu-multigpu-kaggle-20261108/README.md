# Native two-GPU ParamMesh evidence

Captured on 2026-11-08 in a disposable Kaggle T4×2 session from source commit
`51b9d3d36c485ec7bf8c27f92fdb6594bb80014f` (PR #85 branch).

- Host: Linux x86-64, 4 vCPUs, two Tesla T4 devices
- Runtime: Python 3.13.16, PyTorch `2.11.0+cu130`, CUDA `13.0`
- Workload: external linear PyTorch workload, two workers, two shards, workers on
  `cuda:0` and `cuda:1`
- Trials: 9 total; 3 synchronous, 3 asynchronous, 3 bounded-staleness
- Synchronous result: all three trials completed with shard deltas `6,6` and max parameter
  error `2.9802322387695312e-08`
- Archive SHA-256: `afecf76066d6c84165c66b35b48ba4bb2f5123e1a57fe5e202d091458532b379`

`manifest.json`, all trial JSON files, CSV transport records, charts, and
`gpu-validation-summary.json` are the raw captured artifacts. The summary includes per-file
SHA-256 values. The archive was downloaded from the Kaggle notebook output without credentials.

This is native two-GPU worker-placement and correctness evidence for the supported external
linear workload. It is not a claim of multi-node scaling, GPU packaging in the CPU release
image, arbitrary model support, or production performance.
