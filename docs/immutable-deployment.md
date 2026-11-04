# Immutable deployment and rollback

ParamMesh production currently runs through Coolify on the `paramesh-gcp` VM and
uses the digest-qualified GHCR image recorded below. The old application definition
built the mutable `paramesh:local` tag. This workflow keeps the existing Compose
topology and persistent volumes while preventing an immutable deployment from
silently rebuilding a different checkout.

## Build and publish

Builds are tied to a full Git commit and receive OCI revision labels from the
Dockerfile. The manual/tagged [immutable image workflow](../.github/workflows/immutable-image.yml)
publishes `ghcr.io/fetachino/paramesh:sha-<commit>` with `GITHUB_TOKEN`, then
records the registry manifest digest in an artifact. The tag is only a locator;
deployment uses the resulting `image@sha256:<digest>` value.

For a local or controlled build:

```powershell
python scripts/immutable_release.py build `
  --source-commit <40-character-commit> `
  --image-ref ghcr.io/fetachino/paramesh:sha-<commit> `
  --push `
  --output artifacts/immutable-release.json
```

The release manifest records the source SHA, digest-qualified image, Compose
file hashes, compatibility contract, build metadata and (for local `--load`
builds) an optional image archive hash. It contains no environment values or
credentials. `verify` refuses a changed Compose file or a non-digest image:

```powershell
python scripts/immutable_release.py verify `
  --manifest artifacts/immutable-release.json
```

## Compose and Coolify

Use the checked-in override with the existing stack:

```powershell
$env:PARAMESH_IMAGE = "ghcr.io/fetachino/paramesh@sha256:<digest>"
docker compose -f compose.yaml -f deploy/immutable/compose.yaml `
  --profile operations --profile storage config --quiet
docker compose -f compose.yaml -f deploy/immutable/compose.yaml `
  --profile operations --profile storage up -d --no-build
```

The override removes every application `build` section. A missing or mutable
`PARAMESH_IMAGE` therefore fails configuration rather than silently rebuilding
from a different checkout. Infrastructure image tags remain unchanged and the
existing private-network, TLS and HTTPS routing boundaries are preserved.

CI runs `scripts/verify_immutable_compose.py` against the merged configuration. It
fails if application build sections return, if the image is not digest-qualified, or
if named volumes, networks, service mappings or infrastructure images change.

For Coolify, first create and verify the release manifest, then configure the
application to use the same two Compose files (or the equivalent checked-in
Compose deployment setting) and set `PARAMESH_IMAGE` to the complete digest
reference. Disable the application build step and use `up --no-build`. The
current Coolify-generated Compose still has application `build` stanzas: an
ordinary Coolify redeploy without the override is **not** an immutable rollout.
Do not change a live application until an isolated test and an operator-approved
change plan exist.

## Rollback guard and procedure

Rollback is a code-image change, not a model-state rollback. Before any apply:

1. Export an offline whole-run checkpoint and preserve all role volumes, the
   Coolify database/configuration backup and the current release manifest.
2. Verify the candidate manifest and checkpoint metadata:

   ```powershell
   python scripts/immutable_release.py rollback-check `
     --current artifacts/current-release.json `
     --candidate artifacts/previous-release.json `
     --checkpoint-manifest artifacts/checkpoint-manifest.json
   ```

   The guard rejects unknown image identities, incompatible protocol/checkpoint/
   state schemas, unequal shard versions and checkpoints missing coordinator or
   shard metadata. It always reports that explicit operator approval and a
   verified backup are required.
3. Apply only with the same environment, Compose files and retained volumes.
   `rollback-apply` requires a backup marker and refuses execution unless the
   caller explicitly selects `--isolated` or `--production-approved`:

   ```powershell
   python scripts/immutable_release.py rollback-apply `
     --current artifacts/current-release.json `
     --candidate artifacts/previous-release.json `
     --checkpoint-manifest artifacts/checkpoint-manifest.json `
     --project-name paramesh-rollback-test `
     --env-file .env.rollback-test `
     --backup-marker artifacts/backup-verified.txt `
     --isolated --execute
   ```

   The command runs `config --quiet` and `up -d --no-build --no-deps
   --force-recreate`; dependency health is verified explicitly afterward rather
   than allowing a busy host's Compose wait loop to hide the image/state result.
   It never runs `down --volumes`, removes a volume, or restores only one shard.
4. Verify coordinator/shard health, equal versions, checkpoint visibility,
   retained training state, dashboard authentication, HTTPS, metrics, logs and
   traces. If compatibility is uncertain, stop the candidate and restore the
   original image and volumes from the verified backup; do not mix state from
   different topology or schema generations.

The helper requires explicit repeated `--service` selections for production
execution; it rejects an unscoped production recreation. The isolated command
above retains its full-profile behavior. For a retained production run with
completed workers, select only the approved services and validate the actual
Coolify configuration before execution.

## Verified hosted rollback and future redeployment

The [authorized November 4 exercise](evidence/gcp-live-rollback-2026-11-04/README.md)
temporarily ran coordinator, both shards and dashboard on the protected old
image, then restored the exact prior GHCR digest. The workers remained stopped,
the maintenance checkpoint service was absent, and all 12 volumes were retained.
Both shard versions, durable journal records, checkpoint hashes, SQLite
integrity and authenticated HTTPS passed before and after restoration. This
closes the tested compatible-image hosted rollback gate; it does not authorize
an arbitrary image or state migration.

For the **current completed-worker topology**, use this procedure for any
future digest change:

1. Record the running image IDs and OCI revisions, source SHA, current Compose
   and environment-file hashes, checkpoint phase and equal shard versions.
   Confirm no training or checkpoint operation is active. Verify a fresh
   off-host backup covering all role/dashboard SQLite databases, worker
   journals, checkpoint blobs, Coolify configuration/database, Redis and all
   named volumes. Keep secrets and raw backups outside Git.
2. Build from an exact merged commit, publish with `GITHUB_TOKEN`, verify the
   registry digest, OCI revision and platform, and pull by digest on the host.
   Reject incompatible protocol, checkpoint or state-schema contracts. Test
   the proposed digest in isolation before a production approval.
3. Stage the checked-in override in a persistent root-controlled location.
   Render the actual Coolify Compose and environment file with and without it;
   require identical volumes, networks, credentials, ports, HTTPS labels and
   dependencies, with only the approved application image changed and every
   application `build` block removed. Confirm the old image remains locally
   recoverable. Do not use a `/tmp` override.
4. During an approved maintenance window, use `docker compose --dry-run` first.
   Then select **only** `coordinator shard-0 shard-1 dashboard` with
   `up -d --pull never --no-build --no-deps --force-recreate` and the same
   project name, private environment file, base Compose and immutable override.
   Do not include workers or the maintenance checkpoint service. An active
   training run needs its own quiescence and service plan; this command is not
   safe to copy into that situation.
5. Verify actual image IDs, direct coordinator/shard health, equal versions,
   SQLite and journal integrity, checkpoint hashes, HTTPS authentication and
   private backend bindings. Stop on any mismatch and restore the previous
   verified image with the same four-service command if state remains
   compatible. Never delete volumes or restore one shard independently.

The production image remains
`ghcr.io/fetachino/paramesh@sha256:31b6cb80d1fda851536e508cf38b593dcd1135b1fbf94f846c3d840aaba06ba1`
with older OCI source revision `2b1fbae42a5ea15cfa3507baed5f25a2533af33c`.
The v1.0.0 candidate source includes newer PR #39 code and has **not** been
deployed. A future Coolify redeploy must first adopt the build-free override
and an approved digest; clicking redeploy against the current generated
Compose could rebuild from source.
