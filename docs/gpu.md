# Optional GPU execution

Workers accept `--device cuda` (or another PyTorch device string) and move the model and batches
to that device before computing gradients. The runtime must provide a CUDA-enabled PyTorch build
and an available CUDA device; CPU-only installations fail closed with a clear error.

The published lockfile and release image intentionally use CPU PyTorch. Native GPU correctness,
performance, and container packaging are therefore not release claims until a CUDA host and
matching dependency set are tested. The distributed protocol remains float32 and shards retain
CPU/Numpy state, so this is an opt-in worker execution path rather than arbitrary accelerator
support.
