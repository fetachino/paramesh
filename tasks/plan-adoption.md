# ParamMesh adoption expansion plan

This plan extends the already released recovery-first CPU platform without
changing the production deployment or the v1.0.0 tag.

## Phase 1: model-family contract

- [ ] Add deterministic linear, small CNN, and small transformer external-workload examples.
- [ ] Add correctness tests for each example through the existing `TrainingWorkload` interface.
- [ ] Update the supported contract to name the tested families and keep arbitrary-model claims out.

## Phase 2: benchmark matrix

- [ ] Add a measured 1/2/4-worker benchmark runner with raw JSON/CSV and hardware/source metadata.
- [ ] Add a simple PyTorch single-process reference and documented comparison tolerances.
- [ ] Preserve failure/recovery measurements separately from throughput claims.

## Phase 3: installation and recovery UX

- [ ] Make the Python path a single documented command (`uvx`/`pipx` or equivalent) while retaining the Windows executable.
- [ ] Add a one-command recovery demo that captures worker interruption, checkpoint restore, final-state comparison, and dashboard evidence.
- [ ] Add focused tests and documentation for each user path.

## Checkpoint

- [ ] Focused tests pass.
- [ ] Full suite, Ruff, mypy, and packaging checks pass.
- [ ] No production, credential, volume, GHCR, tag, or release changes.

