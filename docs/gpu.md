# Optional GPU execution

Workers accept `--device cuda` (or another PyTorch device string) and move the model and batches
to that device before computing gradients. For a two-worker run, the external benchmark also
accepts `--devices cuda:0 cuda:1` to place each worker on a distinct GPU. The runtime must
provide a CUDA-enabled PyTorch build and an available CUDA device; CPU-only installations fail
closed with a clear error.

The published lockfile and release image intentionally use CPU PyTorch. Native GPU correctness,
performance, and container packaging are therefore not release claims until a CUDA host and
matching dependency set are tested. The distributed protocol remains float32 and shards retain
CPU/Numpy state, so this is an opt-in worker execution path rather than arbitrary accelerator
support.

## Native two-GPU evidence

Kaggle T4×2 validation from commit `51b9d3d36c485ec7bf8c27f92fdb6594bb80014f` ran nine
fresh-process trials (three each for synchronous, asynchronous, and bounded-staleness modes).
Workers used `cuda:0` and `cuda:1`; all three synchronous trials reached shard deltas `6,6`
with max parameter error `2.9802322387695312e-08`. The host reported two Tesla T4 devices,
CUDA `13.0`, and PyTorch `2.11.0+cu130`.

Raw JSON, CSV, charts, and per-file SHA-256 values are preserved in
[`docs/evidence/gpu-multigpu-kaggle-20261108/paramesh-gpu-multigpu-20261108`](evidence/gpu-multigpu-kaggle-20261108/paramesh-gpu-multigpu-20261108).
The downloaded archive SHA-256 is
`afecf76066d6c84165c66b35b48ba4bb2f5123e1a57fe5e202d091458532b379`.
This validates the two-GPU worker placement and correctness smoke workload, not broad scaling,
multi-node networking, CUDA packaging for the CPU release image, or arbitrary model support.
