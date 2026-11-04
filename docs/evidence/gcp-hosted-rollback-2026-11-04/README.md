# Immutable hosted rollback validation — 2026-11-04

This test used the existing `paramesh-gcp` VM but a separate Compose project,
credentials, networks and volumes. The Coolify production project and its
persistent volumes were never changed.

## Source and image identities

- `origin/main` after PR #35: `af183e465e13470e69d0ea4900a6922d10d8c2bc`.
- Candidate image built from exact source `1eacc17be19a02b956351c27f5a7b0223b975c2c`:
  `paramesh@sha256:d2626dba65eff89e37516bf699a72c3aaaf5b18e12cc615202aeee62ad492265`.
- Previous known-good image built from `af183e465e13470e69d0ea4900a6922d10d8c2bc`:
  `paramesh@sha256:4041619ce29a8f083659657ea90a341aa058514b034e965e7b414c0f1bb3c506`.

Both images were built on the Linux VM with OCI revision labels and used by
digest-qualified Compose references. The registry-publishing workflow is
implemented, but this run used locally transferred source/image artifacts because
the workstation GitHub token has no package-write scope.

## State and failure checks

The candidate revision ran the isolated two-worker stack and produced an offline
checkpoint at global step 727 with shard versions `[727, 727]`. The raw volume
archive is preserved in `checkpoint-volume.tgz`; its SHA-256 is recorded in
`archive-checksum.json`, and `checkpoint-manifest.json` preserves all five role
records and shard metadata.

An attempted live checkpoint under the host's 2-vCPU contention failed with the
existing `Cannot freeze a shard with pending synchronous contributions` boundary.
No timeout was increased and the attempt was aborted. The rollback test therefore
used the quiesced offline checkpoint required for persistent-state compatibility.
An invalid digest pull also failed before creating or changing a container.

## Rollback result

`rollback-check` accepted only the digest-qualified previous image, equal-shard
checkpoint, and matching protocol/checkpoint/state compatibility contract. The
guarded `rollback-apply --isolated --execute` recreated the isolated services with
`--no-build` and retained every volume. After the first Compose health-wait timeout
under contention, the no-dependency apply path completed; explicit checks showed:

- coordinator and both shards healthy;
- workers healthy at step 763 after resuming retained state;
- checkpoint manifest still present with the recorded hash;
- dashboard login returned `303` and an authenticated protected API returned `200`;
- no volume reset or single-shard restore occurred.

The isolated project, temporary images, source checkout, credentials and all test
volumes were removed afterward. Production Coolify, HTTPS, credentials, volumes,
and the primary VM remained healthy and unchanged.

## Gate decision

The immutable image and guarded rollback implementation is verified, and the
isolated persistent-state rollback passed. The hosted immutable rollback gate is
**not closed** yet: a registry-backed GHCR artifact and a Coolify deployment using
the digest-qualified override still require an operator-approved cutover. No
production rollback or `v1.0.0` tag was performed.
