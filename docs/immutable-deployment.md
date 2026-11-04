# Immutable deployment and rollback

ParamMesh production currently runs through Coolify on the `paramesh-gcp` VM.
The old application definition built the mutable `paramesh:local` tag. This
workflow keeps the existing Compose topology and persistent volumes, but makes
the application image a digest-qualified artifact before Coolify is changed.

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

   The command runs `config --quiet` and `up -d --no-build --force-recreate`.
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

## Release boundary

The immutable workflow and guard can be tested without changing production. The
hosted rollback gate remains open until an actual registry-backed image is
published, an isolated deployment has exercised a second revision and a real
rollback with persistent-state checks, and any required production cutover is
explicitly approved and verified.
