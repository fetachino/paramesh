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

## Azure Blob and Azurite

The same offline manifest/blob format supports Azure Blob through the official
`azure-storage-blob==12.31.1` SDK in the locked `storage` extra. Supply an explicit
account endpoint, existing container, account name and base64 shared account key.
The adapter never creates accounts/containers or falls through to ambient Azure
profiles. SAS URLs, managed identity and Entra ID authentication are not implemented.
Use HTTPS for remote storage; HTTP is only appropriate for a trusted local emulator.

With credentials already loaded securely into `PARAMESH_AZURE_ACCOUNT` and
`PARAMESH_AZURE_KEY`, and the entire source run stopped:

```powershell
paramesh checkpoint export --id azure-run-20 --state-dir state/cluster --azure-endpoint https://ACCOUNT.blob.core.windows.net --container paramesh-checkpoints
paramesh checkpoint restore --id azure-run-20 --state-dir restored-cluster --azure-endpoint https://ACCOUNT.blob.core.windows.net --container paramesh-checkpoints
```

Replace `ACCOUNT` with the actual account name. `--azure-endpoint` and `--s3-endpoint`
are mutually exclusive. `--container` belongs to Azure and `--bucket` to S3.
The Compose checkpoint helper already includes storage dependencies. Pass Azure
credentials only to that one-shot helper with `-e PARAMESH_AZURE_ACCOUNT -e PARAMESH_AZURE_KEY`;
training/dashboard services do not receive them. The endpoint must be reachable from
the helper's network. No shared Compose service or volume needs replacement.

Writes use Block Blob `overwrite=False`: existing identical objects are verified,
conflicting content fails, and blobs precede conditional manifest publication.
Downloads request at most the limit plus one byte, disable content decompression,
and reject oversized results before checkpoint parsing. Explicit connect/read timeouts
and bounded SDK retries apply. The adapter selects service API `2026-06-06`, supported
by Azurite 3.37.0, without disabling API checks.

```powershell
uv sync --locked --all-extras --python 3.12
python -m pytest tests/test_azure.py -q --basetemp artifacts/azure-check
```

Docker must be running. Tests start a digest-pinned Azurite 3.37.0 container with a
fresh random custom-account key, a random loopback-only Blob port and disposable
container storage; they remove only that container. No standard emulator key or
cloud account is used. Tests cover the real CLI, immutable/idempotent publication,
wrong credentials, object bounds, corrupt blobs, interrupted publication and existing
restore destinations. A partially delivered checkpoint (shard versions 1 and 0)
resumes through real coordinator/shard RPCs, replays one journaled contribution and
matches uninterrupted SGD below `1e-6`; its report remains in the test artifact directory.

This is emulator compatibility evidence, not a managed Azure deployment, durability
SLA or cloud performance measurement. Online coordinated checkpointing and topology
remapping remain unimplemented.

Sources: [Azurite 3.37.0 and supported API](https://github.com/Azure/Azurite/blob/v3.37.0/README.md),
[SDK 12.31.1 changelog](https://github.com/Azure/azure-sdk-for-python/blob/azure-storage-blob_12.31.1/sdk/storage/azure-storage-blob/CHANGELOG.md),
[official BlobClient implementation and contracts](https://github.com/Azure/azure-sdk-for-python/blob/azure-storage-blob_12.31.1/sdk/storage/azure-storage-blob/azure/storage/blob/_blob_client.py).
