# GHCR immutable deployment and rollback — 2026-11-04

This evidence records the first registry-backed ParamMesh deployment using the
exact `origin/main` source after PR #36 and the merged Community Standards change
(PR #32). It used the existing `paramesh-gcp` VM only as an isolated Compose host;
the Coolify production project, credentials, HTTPS route, persistent volumes and
firewall were never changed.

## Published identity

- Main source: `2b1fbae42a5ea15cfa3507baed5f25a2533af33c`.
- GitHub Actions immutable-image run: [41842320861](https://github.com/fetachino/paramesh/actions/runs/41842320861), using the workflow `GITHUB_TOKEN` package permission.
- Published image: `ghcr.io/fetachino/paramesh@sha256:31b6cb80d1fda851536e508cf38b593dcd1135b1fbf94f846c3d840aaba06ba1`.
- Registry index: OCI, native platform `linux/amd64`; the exact index and pull metadata are in [registry-index.json](registry-index.json) and [registry-pull.json](registry-pull.json).
- The pulled image reported OCI revision `2b1fbae…`, source `https://github.com/fetachino/paramesh`, and `source-dirty=false`.

The Linux VM pulled the exact digest and ran application services without a build
step. The immutable Compose override supplied the digest to coordinator, both
shards, dashboard and workers; no mutable tag was used. The complete release
manifests preserve Compose hashes and compatibility contract in
[current-release.json](current-release.json) and [previous-release.json](previous-release.json).

## Isolated run and state

Project `paramesh-ghcr-2b1fbae` used separate networks, credentials and named
volumes. The 40-step synchronous run completed with both workers exiting `0` and
`resumed_from=0`; the dashboard returned `/healthz` `200`, login returned `303`,
and the authenticated protected API returned `200`.

After quiescing the roles, the raw checkpoint `ghcr-verified` recorded global step
40 and equal shard versions `[40, 40]` for all five role records. The exported
manifest and the exact manifest copied from the checkpoint volume are preserved in
[checkpoint-manifest-export.json](checkpoint-manifest-export.json) and
[checkpoint-volume-manifest.json](checkpoint-volume-manifest.json). The complete
checkpoint volume archive is [checkpoint-volume.tgz](checkpoint-volume.tgz); its
SHA-256 and manifest checksum are in [archive-checksum.json](archive-checksum.json).

## Digest-qualified rollback

The candidate previous image was
`ghcr.io/fetachino/paramesh@sha256:a715e03c948d4cd234fbd0a161e5f5d55d632b01100d9d92178909ec1b2277f1`,
source `d7ee8eb212369f16b67e7ad7a7afb0509b290089`. The guard accepted the two
compatible manifests and equal-shard checkpoint ([rollback-check.json](rollback-check.json)).
With the verified backup marker and `--isolated --execute`, the rollback recreated
the isolated services with `--no-build --no-deps --force-recreate` and did not reset
volumes. All application containers, including both workers, reported the candidate
digest. Workers exited `0`; coordinator logs recorded both `worker_recovered` events
and `training_completed` at step 40. Direct dashboard health/authentication checks
remained `200`/`303`/`200`, and the checkpoint manifest remained present.

The ordinary Compose health probes timed out on this 2-vCPU host while production
and the isolated stack competed for CPU. This was not treated as an image or state
failure: direct endpoint, container identity, event-log and retained-volume checks
were collected instead. No timeout was increased and no volume was reset.

## Cleanup and gate decision

The isolated Compose project, its exact named volumes, temporary source checkout,
temporary credentials and both test image digests were removed. No VM or firewall
rule was created. A read-only production check afterward showed the Coolify,
coordinator, shard, dashboard, storage and observability containers healthy; the
public HTTPS health endpoint still returned `200`.

The following requirements pass:

- GHCR publication from the exact main SHA using Actions-scoped package access.
- OCI digest, revision metadata, platform and Linux registry pull verification.
- Isolated digest-qualified Compose deployment without rebuilding.
- Guarded isolated rollback with compatible retained state, equal-shard checkpoint,
  worker completion/recovery and authenticated dashboard checks.
- Raw checkpoint manifest/archive preservation with checksums and cleanup.

Production Coolify cutover and any live production rollback remain pending explicit
operator approval. The current production Compose definition still uses
`paramesh:local`; the precise cutover/restore procedure is documented in
[immutable-deployment.md](../../immutable-deployment.md) and [coolify.md](../../coolify.md).
This evidence does not close the live hosted rollback gate and does not justify a
`v1.0.0` tag by itself.
