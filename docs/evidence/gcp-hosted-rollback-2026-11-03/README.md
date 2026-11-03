# Hosted rollback investigation — 2026-11-03 UTC

This investigation used the existing `paramesh-gcp` Google Cloud VM and left the
production deployment running throughout. No application source, VM, firewall rule,
credential, named volume or checkpoint was deleted or replaced.

## Why Coolify shows no rollback images

The production Compose file builds the application as `paramesh:local`. The running
containers carry Coolify build fingerprint
`6ca0b96faaee1e7ec399290776f8eaf88f2990ea43bf84592f07b1fcf0ab980a`, but the
application image does not contain a Git revision label. The current local image is:

```text
paramesh:local
sha256:913b68db7a61dacf13beed4a475404f49b28a7e413f2b089041d320a5fcec042
created 2026-11-03T20:35:23Z
```

The VM also has these older images:

```text
paramesh:mh-a3486e3
sha256:8a96fd8a4518617894c5e06bb4040adc7a8ce69a48f3a85aa2c2d1baa73416fd

paramesh:mh-379c340
sha256:1a3705871c503b388ef02e5294fed631d48a8219003c9f9f837173d37c534b26
```

Those `mh-*` tags came from the earlier multi-host trial; they are not prior
Coolify deployment records. Coolify's rollback panel therefore correctly reports
no saved rollback images: a local Compose build tag is rebuilt/replaced, and no
registry-backed immutable image history was configured.

## Recovery artifact and checks

Before any live test, a root-only backup was created at
`/var/backups/paramesh-rollback-20261103` on the VM. It contains:

| Artifact | Observed size | Purpose |
| --- | ---: | --- |
| `paramesh-local.tar.zst` | 311 MB | Current image exported from `paramesh:local` |
| `paramesh-state.tar.zst` | 184 MB | Coolify `.env`, Compose file, all ParamMesh named volumes and telemetry volumes |
| `coolify-db.sql` | 1.4 MB | Coolify deployment metadata and credentials database dump |
| `SHA256SUMS` | — | Hashes for all three backup artifacts |

All three archive hashes returned `OK` with `sha256sum -c`. Files are owned by
root with mode `0600`; no values or credentials are included in this repository.
The backup was created without stopping containers, and the live endpoint stayed
healthy afterward.

The candidate `paramesh:mh-a3486e3` was tagged locally as
`paramesh:rollback-a3486e3` and addressed by its immutable image ID. In an isolated,
network-disabled, read-only temporary container it passed:

- Python runtime smoke check (`3.12.16`)
- `paramesh --version` (`0.1.0`)
- CLI help exposing coordinator, shard, worker, dashboard and checkpoint commands

The production containers remained healthy and continued using `paramesh:local`.
The named volumes remained present, including coordinator, both shard states,
dashboard state, checkpoints, Grafana, metrics, logs, traces and object storage.

## Safe procedure and limitation

The recoverable procedure is: preserve the current image and volume backup; record
the source revision, image digest, Compose configuration and environment checksum;
validate the candidate in an isolated container; deploy only an immutable candidate
digest with the same environment; then verify health, HTTPS/login, retained training
step, checkpoint visibility and telemetry before declaring success. If compatibility
fails, stop the candidate and restore the original image and volumes from the backup.
Never use `docker compose down --volumes` or restore only one shard.

A live rollback was deliberately **not** performed. The current Coolify application
has no saved rollback image and its Compose build uses the mutable `paramesh:local`
tag, while the candidate lacks an embedded source revision proving exact
source-to-image identity. Replacing the tag live would therefore be a disruptive,
untraceable experiment rather than a release-quality rollback test. Hosted rollback
remains a release blocker until an immutable registry/digest deployment artifact (or
an equivalent Coolify-managed prior image with source traceability) is established.
