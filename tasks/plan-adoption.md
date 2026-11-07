# ParamMesh adoption expansion plan

This plan extends the already released recovery-first CPU platform without
changing the production deployment or the v1.0.0 tag.

## Phase 1: model-family contract

- [x] Add deterministic linear, small CNN, and small transformer external-workload examples.
- [x] Add correctness tests for each example through the existing `TrainingWorkload` interface.
- [x] Update the supported contract to name the tested families and keep arbitrary-model claims out.

## Phase 2: benchmark matrix

- [x] Add a measured 1/2/4-worker benchmark runner with raw JSON/CSV and hardware/source metadata.
- [ ] Capture and publish a clean-source 1/2/4-worker matrix; results must remain raw and host-specific.
- [ ] Add a simple PyTorch single-process reference and documented comparison tolerances.
- [ ] Preserve failure/recovery measurements separately from throughput claims.

## Phase 3: installation and recovery UX

- [ ] Make the Python path a single documented command (`uvx`/`pipx` or equivalent) while retaining the Windows executable.
- [x] Add a one-command recovery demo that captures worker/shard interruption, numerical recovery, and dashboard evidence.
- [ ] Extend the recovery demo with a coordinated checkpoint-abort/resume walkthrough before claiming full checkpoint UX.
- [ ] Add focused tests and documentation for each user path.

## Checkpoint

- [ ] Focused tests pass.
- [ ] Full suite, Ruff, mypy, and packaging checks pass.
- [ ] No production, credential, volume, GHCR, tag, or release changes.

