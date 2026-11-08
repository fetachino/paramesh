# Native CUDA smoke evidence

This is a real local CUDA validation run from merged `main` at
`83f405045ff7567ee7ebb755ba4b4eaa12c3eed7`.

- Host: Windows AMD64 with NVIDIA GeForce RTX 4080
- Runtime: Python 3.12.10, PyTorch `2.11.0+cu128`
- Workload: synchronous two-worker, two-shard linear demo; 20 steps per worker
- Result: both workers completed; shard versions `20,20`; `failure: null`
- Numerical check: max parameter error `1.1920928955078125e-07`
- Raw result: `gpu-demo-main-20261108.json`
- SHA-256: recorded in `SHA256SUMS`

This closes native CUDA correctness smoke validation for the supported demo
workload. It does not claim broad GPU performance scaling, multi-GPU support,
or arbitrary PyTorch model compatibility.
