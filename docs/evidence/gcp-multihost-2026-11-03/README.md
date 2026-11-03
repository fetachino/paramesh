# Google Cloud two-host verification, 2026-11-03

This is a real two-VM Google Cloud Compute Engine test in `us-central1-a`,
separate from the primary VM's existing Coolify application. Both VMs ran
Ubuntu 24.04, x86-64, `e2-standard-2`. The primary host (`10.90.0.2`) ran the
coordinator, shard 0, dashboard, NATS, Prometheus, Grafana, Loki and Tempo.
The temporary second host (`10.90.0.3`) ran shard 1 and both workers. The test
used a distinct Compose project, image tag, credentials, certificates and named
volumes; it did not replace Coolify's production project. The application source
was `379c340b0f690d590e1f4aaf5ff54fc3fb5208ad` plus the checkpoint helper
overlay change in this evidence PR. The [operations report](operations.json)
records `dirty: true` for that reason.

The shared run ID was `gcp-mh-20261103`, with two workers, two shards,
synchronous mean aggregation, learning rate 0.05 and 30-second gradient barrier.
RPC used mTLS and distinct data/admin tokens; NATS used TLS and token auth.
Prometheus and OTLP used private HTTP. GCP firewall rules admitted only the two
private host IPs to the training, event, trace and metric ports. An external
TCP probe from the operator PC found the tested ports closed or filtered on
both public IPs. A valid-format wrong RPC token returned `UNAUTHENTICATED`;
omitting the client certificate returned `UNAVAILABLE` with a closed TLS socket.

The [raw operations probe](operations.json) was recorded during active training.
It found both workers and both shards, six healthy scrape targets, worker
counters, authenticated dashboard access, lifecycle records in Loki, NATS
events, and a Tempo trace spanning worker 0 and both shards. The sampled
coordinator step and shard versions differ by a few steps because the report
reads them while training continues. This is an operations probe, not a
controlled performance benchmark. Grafana was healthy, but this report does
not record a browser session or a panel screenshot.

Two initial live checkpoint attempts at the normal 0.1-second step delay timed
out waiting for both workers to acknowledge. In each case one worker was blocked
on a synchronous shard barrier after its peer paused at the checkpoint boundary;
the blocked RPC timed out, and the worker could not re-register until the epoch
was aborted. Both uncommitted epochs were explicitly aborted, and training
resumed. This is a real limitation, not a successful high-rate checkpoint claim.

With the same persisted run and a controlled 120-second step delay, both workers
acknowledged at step 1399. The live helper published the five-role
[immutable manifest](checkpoint-manifest.json) with shard versions `[1399, 1399]`;
the helper reported 93.46 seconds from invocation to completion, including
the deliberate delay. The restore command validated the manifest and created
fresh coordinator, shard and worker SQLite files in a separate destination.
It did not start a second cluster from the restored files or store a backup
outside the primary VM. After coordinator and shard 0 restarted on the primary
host and shard 1 restarted on the second host, the
[coordinator status](post-restart-status.json) showed both workers healthy at
step 1404, with increased session generations and the committed checkpoint
still recorded. The workers were then stopped to avoid the 120-second delay
continuing for hours.

This test proves cross-host connectivity, training, observability, controlled
checkpoint publication/restore validation, and process restart persistence.
It does not prove high-rate synchronous checkpoint reliability, restored-run
resume, host or network interruption recovery, public HTTPS, WAN scaling,
native ARM64, or a performance improvement from adding a host. The temporary
VM must be removed after remaining tests and evidence collection.
