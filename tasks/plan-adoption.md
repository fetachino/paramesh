# ParamMesh adoption expansion plan

This plan extends the already released recovery-first CPU platform without
changing the production deployment or the v1.0.0 tag.

## Phase 1: model-family contract

- [x] Add deterministic linear, small CNN, and small transformer external-workload examples.
- [x] Add correctness tests for each example through the existing `TrainingWorkload` interface.
- [x] Update the supported contract to name the tested families and keep arbitrary-model claims out.

## Phase 2: benchmark matrix

- [x] Add a measured 1/2/4-worker benchmark runner with raw JSON/CSV and hardware/source metadata.
- [x] Capture and publish a clean-source 1/2/4-worker matrix; results remain raw and host-specific in [the November 7 capture](../docs/evidence/benchmarks/scaling-matrix-local-2026-11-07/README.md).
- [x] Add a simple PyTorch single-process reference and documented comparison tolerances.
- [x] Preserve failure/recovery measurements separately from throughput claims.

## Phase 3: installation and recovery UX

- [x] Add the packaged `paramesh-local` entry point while retaining the Windows executable.
- [ ] Publish the train extra through a trusted package channel so `pipx install
      "paramesh[train]"` is usable by outside evaluators. The manual OIDC workflow
      and setup instructions are ready; publication remains intentionally gated on
      the next immutable release tag and PyPI publisher configuration.
- [x] Add a one-command recovery demo that captures worker/shard interruption, numerical recovery, and dashboard evidence.
- [x] Extend the recovery documentation with a coordinated checkpoint-abort/resume walkthrough; the real two-host result is preserved in the checkpoint gate evidence.
- [ ] Add focused tests and documentation for each user path.

## Checkpoint

- [x] Focused tests pass.
- [x] Full suite/CI, Ruff, mypy, and packaging checks pass for the merged slices.
- [x] No production, credential, volume, GHCR, tag, or release changes.

