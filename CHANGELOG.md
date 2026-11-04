# Changelog

## 1.0.0 — release candidate (not tagged or published)

### Added

- Independent coordinator, parameter-shard and CPU worker processes with
  synchronous, asynchronous and bounded-staleness SGD.
- Durable update receipts, worker journals, lease fencing and whole-run
  checkpoints with local, S3-compatible and Azure Blob backends.
- Authenticated operator dashboard and private Prometheus, Grafana, Loki,
  Tempo and NATS operations stack.
- Locked Python dependencies, immutable GHCR image workflow and a
  digest-qualified Compose override.

### Fixed

- High-rate synchronous checkpoint completion and Windows barrier recovery
  races, with repeated regression and real two-host checkpoint evidence.
- Worker recovery after ambiguous RPC delivery without duplicating committed
  updates or losing journaled work.

### Verified

- One native Google Cloud x86-64 Coolify host with HTTPS, persistent state and
  a compatible-image live rollback followed by exact GHCR restoration.
- A separate two-host x86-64 checkpoint correctness and recovery trial.
- Local SeaweedFS and Azurite checkpoint behavior; Azure Blob uses the real
  SDK against Azurite, not a managed Azure deployment.

The [release notes](docs/releases/v1.0.0.md) define supported environments,
installation, known limits and the unpublished image-verification gate.
