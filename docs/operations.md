# Operate the local stack

Use the repository's `compose.yaml` for training and optional operations/storage.
No managed cloud account is needed. Operations add several CPU/memory consumers;
their displayed timings are observations of this machine, not scaling claims.

```powershell
python scripts/quickstart.py
```

This creates the clone's ignored credentials before starting Compose and prints
the dashboard and Grafana URLs. Use `--no-build` to reuse an existing local image.
The equivalent individual commands are:

```powershell
python scripts/create_dev_env.py --operations
docker compose --profile operations up --build -d
docker compose exec coordinator paramesh status --coordinator coordinator:50050
python scripts/verify_operations.py
```

On a fresh clone, run `python scripts/create_dev_env.py --operations` before
starting the operations profile. It creates that clone's own Git-ignored `.env`
with distinct development credentials and local operations defaults; the
repository contains no shared passwords or secrets. Rerunning the generator
preserves existing values and adds only missing settings.

Open `http://127.0.0.1:8080` for ParamMesh and `http://127.0.0.1:3000` for Grafana.
Both use username `operator`; read their separate generated passwords from this
clone's `.env`: `PARAMESH_DASHBOARD_PASSWORD` and `PARAMESH_GRAFANA_PASSWORD`.
Never paste them into reports or URLs.
The operations flag supplies a 1,000-step target and 0.05s deliberate pacing only
when those settings are absent. Increase the target to continue retained training.
Pacing is outside the training-step trace and step-duration histogram.

The dashboard is read-only; refresh/pause changes browser observation, not training.
Its state and loss/throughput samples have different collection times. A lower
coordinator step than shard version is expected between heartbeats. Expired cookies
return to sign-in; service restart or sign-out invalidates all operator sessions.
The UI shows unknown/unavailable signals explicitly. Trace sampling defaults to 20%;
the generated demonstration environment uses 100% for visible local evidence.

For a separate bounded-lag demonstration, set `PARAMESH_CONFIG=examples/compose-bounded.json`
and use a **fresh Compose project with fresh role volumes**, plus different loopback UI
ports. This fixture retains run ID `compose-demo` for the included shard health checks.
Never switch a retained project's mode/configuration; durable fingerprints reject it.
The original `examples/compose.json` remains the synchronous default.

## Services and boundaries

| Service | Access and storage |
| --- | --- |
| Coordinator, shards, workers | Internal authenticated gRPC; five durable state volumes |
| NATS | Private operations bridge; separate token; lifecycle JSON only |
| Prometheus | Private scrape/query; 2s scrapes; at most 24h / 512MB retention |
| Tempo | Private OTLP HTTP and query API; persisted local blocks/WAL |
| Loki | Private HTTP; persisted lifecycle JSON; 24h retention |
| Grafana | Loopback port 3000; separate operator credential; provisioned dashboard |
| ParamMesh dashboard | Loopback port 8080; one operator; persisted latest 200 validated events |
| SeaweedFS | Optional storage profile; private S3 endpoint and persistent objects |

Tempo/Loki upstream images are distroless and contain no shell/wget. Their actual
HTTP readiness endpoints are checked by the dashboard and the integration verifier.
Other persistent services expose Compose health checks; completed workers are jobs,
not unhealthy daemons. UI publishing requires a normal management bridge in addition
to internal bridges. No training, broker or backend host port is published.

## What the signals mean

| Signal | Meaning / limit |
| --- | --- |
| Global step | Minimum completed iteration reported by configured workers |
| Active workers | Healthy live coordinator leases; completed workers are excluded |
| Loss | Worker batch MSE before its latest update; no fabricated validation metric |
| Steps / examples per second | Prometheus counter rates over 30s; resets handled by `rate` |
| Shard version | Actual durable shard-local SGD commit counter |
| Staleness | Latest accepted version lag per worker/shard, not a cluster-wide SSP clock |
| Pull/push latency | Application RPC latency; pushes include shard barrier/commit waits |
| Bytes | Serialized protobuf payload, excluding HTTP/2 framing and TLS overhead |
| Rejected updates | Server-side rejected push statuses, including authentication denials |
| Pending / in-flight | Actual shard barrier contributions and active RPC counts |
| Event queue / drops | Bounded publisher queue and known lost/unconfirmed deliveries |
| Checkpoint duration | Offline export duration observed on `checkpoint_completed` |

Metrics labels are bounded to methods, statuses, configured workers and Compose
components. Run IDs, trace IDs and arbitrary error strings are not metric labels.
Histogram p95 values are bucket estimates, not exact percentiles.
The Grafana dashboard is generated with `python scripts/generate_grafana.py` and
provisioned from `ops/grafana/`; CI checks for generated-file drift.

## Lifecycle and trace limits

NATS events are allowlisted, at most 4KiB and never carry tensors or credentials.
Training makes a nonblocking enqueue into a 256-item queue. Broker outages can
drop events; the metrics report known loss. Core NATS has no replay guarantee and
loss is not always detectable after a process dies. Events never authorize recovery.
The coordinator and shard databases remain authoritative. Local service stderr
contains structured lifecycle records, including optional trace/span correlation.

The dashboard's bounded subscriber persists validated events before mirroring to
Loki. A Loki failure leaves local history available and increments an error counter;
there is no guaranteed replay or durable event delivery. OTel uses a bounded export
queue and finite network timeouts. Exporter failure must not become an SGD dependency.
The test suite verifies actual training with a broker outage and a full publisher queue.

Traces cover individual worker steps, server RPCs and `shard.aggregate_sgd_commit`.
Sampling and flush timing can omit a step; no trace is a cross-shard transaction.
Tempo search IDs are validated and left-padded to canonical 32-digit W3C IDs,
because [Tempo search can trim leading zeros](https://github.com/grafana/tempo/issues/5395).
Pause browser updates to inspect a chosen trace without its list refreshing.

## Publish a real offline checkpoint event

Wait for workers to complete, or stop all five training roles at a recoverable cut.
Keep the operations services running so the publication event can be observed.

```powershell
docker compose stop worker-0 worker-1 coordinator shard-0 shard-1
docker compose run --rm --no-deps checkpoint checkpoint export --id operator-cut --state-dir /cluster --store /checkpoints
docker compose up -d coordinator shard-0 shard-1 worker-0 worker-1
```

Use a new checkpoint ID for each distinct cut. Existing immutable content is not
overwritten. The Recovery screen distinguishes the latest observed publication
from a recorded whole-run restore check. Follow [checkpoint commands](checkpoints.md)
for actual S3 export/restore and installation into fresh volumes. Publication alone
does not prove a restore succeeded.

For a failure demonstration, kill a running worker, keep it down past the 15s lease
expiry, then start it against its retained volume. Synchronous barriers can time
out at 30s; the supervisor may also restart the waiting peer before progress resumes.
Use `paramesh demo --failure worker` for reproducible measured numerical evidence.

## Reproduce the backend acceptance check

```powershell
python scripts/verify_operations.py --isolated
```

This creates a unique owned project with random loopback UI ports, waits for actual
backend readiness, trains 100 deliberately paced steps, verifies worker counters,
Loki events, a cross-process Tempo trace and private service ports, and removes its
own synthetic volumes. It writes `artifacts/operations-stack.json`. The CI container
job runs it after the separate local/S3 checkpoint verifier. Retained reports record
their source revision and whether they came from an uncommitted development tree.

No Coolify public deployment or multi-machine performance result is claimed.
