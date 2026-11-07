# Supported contract

This document is the current adoption boundary for ParamMesh. It records what
the project has actually tested; it is not a promise of arbitrary model or
cluster support.

## Supported evaluation paths

- **Standalone Windows evaluation:** Windows 10/11 AMD64, the bundled `paramesh-try.exe`,
  two local workers, two local parameter shards, synchronous CPU training, and a
  disposable JSON/browser report.
- **Packaged local evaluation:** the `paramesh-local` entry point exposes the same
  no-Docker result page once the package is installed with the `train` extra.
- **Developer workflow:** Python 3.12 with the locked dependencies on Windows AMD64,
  Linux x86-64, or Linux ARM64 where the locked wheels are available.
- **Team/operations workflow:** Docker Compose on a Linux x86-64 host with the
  authenticated dashboard, persistent state, checkpoints, worker recovery, and
  Prometheus/Grafana/Loki/Tempo/NATS operations services.

## Workload and state boundaries

- The external Python API accepts a spawn-safe model factory and per-worker dataset
  factory with compatible finite float32 parameter tensors.
- The repository has verified external examples for three small CPU model families:
  a linear regressor, an image-shaped convolutional network, and a sequence-shaped
  transformer encoder. Run them with `python examples/external_model_families.py
  linear`, `cnn`, or `transformer`.
- The bundled CLI and checkpoint validator support the deterministic reference MLP.
- These examples define the current tested contract; they do not imply arbitrary
  PyTorch model, optimizer, device, or distributed-data-loader support.
- Checkpoint restore requires compatible parameter names, shapes, dtype, optimizer
  settings, shard count, and protocol/state schema. Do not mix incompatible shard
  volumes or restore into a live run.
- The system is CPU-focused. GPU scheduling, arbitrary model packaging, coordinator
  consensus, high availability, and managed multi-tenant operation are not supported
  claims.

## What adoption feedback should measure

Use the [adoption feedback template](adoption-feedback-template.md) without sending
credentials, customer data, private logs, or checkpoint contents. Record setup time,
first-run outcome, platform, workload shape, recovery expectations, and the smallest
blocker encountered.

This contract will change only when repeated independent-user evidence justifies it.
