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
reference. Disable the application build step and use `up --no-build`. Do not
change the live application until the isolated test below passes and an
operator-approved change plan exists.

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

The production flag is intentionally separate from the isolated flag. A real
production cutover or rollback requires an explicit operator approval with the
current/proposed digests, backup hashes, expected downtime, state-compatibility
risk and restoration steps documented first.

## Planned live rollback exercise

This exercise is prepared but intentionally not executed. The currently deployed
image is
`ghcr.io/fetachino/paramesh@sha256:31b6cb80d1fda851536e508cf38b593dcd1135b1fbf94f846c3d840aaba06ba1`.
The rollback artifact is the protected `paramesh:local` archive from the November 4
preflight, whose image ID is `sha256:913b68db7a61dacf13beed4a475404f49b28a7e413f2b089041d320a5fcec042`.
Its archive, the five SQLite snapshots, checkpoint volume, Coolify configuration,
PostgreSQL dump and Redis dump have independent SHA-256 records outside Git.

Before approval, confirm the same equal-shard checkpoint and all role databases are
readable by both images. Quiesce training with completed workers left stopped, mark
the maintenance window (budget 5–10 minutes on the 2-vCPU VM), and verify the backup
checksums. Then, using the same project, environment, named volumes and immutable
Compose override:

1. Stop only the running ParamMesh application roles; never use `down --volumes`.
2. Load the protected archive and switch all seven application references to the
   restored image, leaving Coolify, proxy, databases and observability untouched.
3. Verify image identity, coordinator/shard health, step and parameter versions,
   SQLite integrity, checkpoint manifest/blob hashes, HTTPS authentication and the
   private-service boundary. Do not start completed workers.
4. Stop immediately on a digest mismatch, unequal shard versions, missing manifest,
   failed authenticated health check, unexpected worker start, or sustained resource
   contention. Restore the GHCR digest and repeat the same health checks.
5. After the rollback observation, restore the GHCR digest even if the old image
   appears healthy, then verify the production state again. Preserve both image
   identities and all command output in the private deployment evidence directory.

No live rollback claim or release tag is justified until this sequence is explicitly
approved, completed, and the current digest is restored successfully.

## Release boundary

The immutable workflow and guard can be tested without changing production. The
[2026-11-04 local-image validation](evidence/gcp-hosted-rollback-2026-11-04/README.md)
and the [2026-11-04 GHCR validation](evidence/gcp-ghcr-rollback-2026-11-04/README.md)
preserved checksummed checkpoint archives and completed retained-state isolated
rollbacks. The GHCR publication, OCI identity, Linux pull and digest-qualified
Compose rollback are now verified. The production Coolify cutover to
`sha256:31b6cb80d1fda851536e508cf38b593dcd1135b1fbf94f846c3d840aaba06ba1` is
complete. The hosted rollback gate remains open only for the separately approved
live restoration exercise.
