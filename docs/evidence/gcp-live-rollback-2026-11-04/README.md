# Hosted live rollback and restoration — 2026-11-04

The authorized exercise ran on the existing single Google Cloud x86-64 VM. Four
running ParamMesh services (coordinator, both shards and dashboard) temporarily
used the protected original `paramesh:local` image, then returned to the exact
pre-existing GHCR digest. Both switches used the checked-in immutable Compose
override, `--pull never --no-build --no-deps`, and an explicit four-service list.
Coolify's application settings, infrastructure containers and all 12 named
volumes were retained. Neither completed worker nor the inactive maintenance
checkpoint service was started.

The [sanitized result](results.json) records the source and image identities,
times, state checks and limitations. Before the switch, a protected VM backup
and an off-host copy were checksum-verified. They covered eight online SQLite
backups (including dashboard and worker journals), the project volumes,
checkpoint data, Coolify configuration, PostgreSQL and Redis. The backup files,
credentials, raw deployment logs and authenticated session material remain
outside Git.

During rollback and after restoration, both shard versions stayed at 1,000;
direct shard checks passed; all eight live SQLite databases passed integrity
checks; the five durable training records matched their backup checksums; and
the checkpoint manifest and five blobs matched their hashes. HTTPS login,
authenticated state access and anonymous API rejection passed on both images.
The final four application containers were healthy on the original GHCR digest.

This closes the **hosted compatible-image rollback gate** for the tested
checkpoint and topology. It does not prove high availability, an arbitrary
version migration, or a bound on public downtime: continuous availability was
not measured. Stopped worker containers retained the GHCR image during the
temporary switch, but no mixed-version worker process ran. Coolify-generated
Compose still contains build stanzas; follow the
[immutable redeployment procedure](../../immutable-deployment.md) before any
future image change.
