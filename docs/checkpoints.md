# Whole-run checkpoints

Continuous recovery uses the most recent local SQLite commit. A portable checkpoint
is a separate **offline whole-run cut**: coordinator metadata, every shard's data-only
protobuf snapshot, and every worker's write-ahead journal. Stop all training services
before export. Exclusive OS leases reject live databases; no hot global snapshot is
claimed. A worker interrupted between shard commits can resume its original requests.

The manifest records the durable completed-step lower watermark, actual per-shard
versions, fixed membership, SGD configuration and content-addressed SHA-256 blobs.
Unequal shard versions remain visible. Stateless SGD has no momentum buffers; other
optimizers are unsupported. Tokens, private keys and live coordinator sessions are
never checkpointed. The store is trusted operator-controlled infrastructure: checksums
detect corruption, not a malicious operator replacing both manifest and data.

## Native layout and commands

Use a directory per role when starting native services:

```text
cluster/
  coordinator/coordinator.sqlite
  shard-0/shard-0.sqlite
  shard-1/shard-1.sqlite
  worker-0/worker-0.sqlite
  worker-1/worker-1.sqlite
```

For example, start the coordinator with `--state-dir cluster/coordinator`, shard 0
with `--state-dir cluster/shard-0`, and worker 0 with `--state-dir cluster/worker-0`.
The checkpoint schema supports configured membership up to the protocol limits.
Worker IDs cannot collide with `coordinator` or `shard-N` service names.

After stopping the complete run:

```powershell
paramesh checkpoint export --id run-20 --state-dir cluster --store artifacts/checkpoints
paramesh checkpoint restore --id run-20 --state-dir restored-cluster --store artifacts/checkpoints
```

Restore requires a destination that does not exist. It validates every checksum,
configuration/model fingerprint, receipt/journal relationship, generation and
manifest summary before publishing the directory. `restored-cluster/run.json`
contains the original run configuration. Restart each role with that configuration
and its corresponding restored state directory. Workers need a step target at least
their saved step. Endpoints and shard ownership must remain the same; topology
remapping is not yet supported. Only the bundled deterministic MLP workload is
currently supported by the CLI and checkpoint validator.

## Compose export and fresh-volume installation

Generate credentials without printing them (existing values are preserved):

```powershell
python scripts/create_dev_env.py
docker compose stop worker-0 worker-1 coordinator shard-0 shard-1
docker compose run --rm --no-deps checkpoint checkpoint export --id run-20 --state-dir /cluster --store /checkpoints
docker compose up -d --no-build coordinator shard-0 shard-1 worker-0 worker-1
```

This writes to the current project's named `checkpoints` volume. To restore into a
**new** project with empty state volumes, mount the source backup volume explicitly:

```powershell
docker compose --project-name paramesh-restored run --rm --no-deps --volume paramesh_checkpoints:/checkpoints checkpoint checkpoint install --id run-20 --state-dir /cluster --store /checkpoints
docker compose --project-name paramesh-restored up -d --no-build coordinator shard-0 shard-1 worker-0 worker-1
```

Replace `paramesh_checkpoints` with the verified source project's actual volume name
when using another project name. `install` refuses any nonempty role volume, including
an interrupted prior installation. It writes `.restore-incomplete` markers before
state, and clears the coordinator's marker last. CLI services refuse startup while
their marker exists. On failed installation, retain the original checkpoint and
inspect the failure; retry against new empty volumes. Existing training volumes are
never overwritten or deleted by these commands.

## S3-compatible storage without cloud charges

Install `.[storage]` for native S3 access; the container image includes it. The SDK
requires an explicit endpoint, bucket and `PARAMESH_S3_ACCESS_KEY` /
`PARAMESH_S3_SECRET_KEY`. It does not fall through to unrelated AWS profiles.
Use HTTPS for remote endpoints. Plain HTTP is appropriate only inside a trusted
private network, such as the local Compose storage network.

```powershell
docker compose --profile storage up -d --wait seaweedfs
docker compose stop worker-0 worker-1 coordinator shard-0 shard-1
docker compose run --rm --no-deps checkpoint checkpoint export --id s3-run-20 --state-dir /cluster --s3-endpoint http://seaweedfs:8333 --bucket paramesh-checkpoints
docker compose up -d --no-build coordinator shard-0 shard-1 worker-0 worker-1
```

SeaweedFS 4.51 is pinned, authenticated from startup, persistent and has no host
ports. Its administrative UIs are private. The checkpoint helper alone connects
to storage and an outbound management network; training services receive no S3
credentials. Missing storage credentials stop SeaweedFS instead of starting anonymous
access. The S3 adapter uploads blobs first, then conditionally publishes the manifest
using `If-None-Match: *`. Retrying identical objects is safe; conflicting contents
fail. Incomplete uploads have no completed manifest and cannot be restored. Unreferenced
blobs can remain after failed publication; automatic garbage collection is deferred.

The native `tests/test_s3.py` suite starts its own temporary authenticated SeaweedFS
container, binds only a random loopback S3 port, checks actual writes/reads, conditional
publication, size bounds and wrong credentials, and removes its own container.
Docker must be running for the full suite. No AWS account or paid provisioning is used.

Sources: [SeaweedFS mini](https://github.com/seaweedfs/seaweedfs/wiki/Quick-Start-with-weed-mini),
[Boto3 PutObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html).

Azure Blob can implement the same immutable object contract. Azure/Azurite, online
coordinated checkpointing and cross-topology restore are separate follow-up work.
