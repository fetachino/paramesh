# CUDA benchmark matrix

This matrix was measured locally on merged ParamMesh source commit
`9da1e9139d7e5e3d3b993323c56a605840be9fdf` using a Windows AMD64 host with an
NVIDIA GeForce RTX 4080, PyTorch `2.11.0+cu128`, and the locked dependency
inputs recorded in `manifest.json`.

- Device: CUDA, one GPU
- Topology: two workers and two shards
- Modes: synchronous, asynchronous, bounded staleness
- Repetitions: three per mode
- Warm-up/measured steps: 2/6
- RPC failures: zero in every trial
- Synchronous max parameter error: `1.1920928955078125e-07`
- Raw trials: `trial-*.json`; tabular outputs: `trials.csv`, `rpc.csv`
- Charts: `overview.png`, `overview.svg`

This is a controlled single-GPU smoke benchmark, not a multi-GPU or GPU
scaling claim. The workstation was not isolated from background load, so the
numbers are reproducibility evidence rather than a performance guarantee.
