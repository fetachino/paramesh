# Architecture

## Control plane

One coordinator serves one immutable run configuration. Configuration includes
the run ID, fixed worker membership, ordered shard endpoints, synchronization mode,
learning rate, aggregation rule and barrier timeout. Run creation is currently a
local JSON configuration operation, not a mutable remote API.

Workers register using protocol version 1 and an allowed worker ID. A random
session token identifies a control-plane lease. A live identity cannot be claimed
twice. The coordinator uses a monotonic clock: a node is initially `registered`,
then `healthy` after a heartbeat, `suspect` after 5 seconds and `unavailable` after
15 seconds. Thresholds can be set when constructing the coordinator. A completed
worker remains `completed`, rather than appearing as a failed node later.

Expired workers may register a fresh control-plane session; old tokens cannot
send heartbeats. The coordinator durably reserves a monotonically increasing
generation, fences it on every shard, then issues the new session. An interrupted
partial fence never reuses a generation. Shard updates reject superseded generations.

Run configuration, generation counters and progress survive in checksummed SQLite
state. Restart invalidates prior leases and requires re-registration; it does not
pretend saved monotonic-clock timestamps are live leases. `global_step` is a
reported completed-step lower watermark across configured workers, not a global
atomic model version. Shard endpoints remain configured; dynamic registration
and coordinator replication are not implemented.

## Data plane and ownership

Workers talk directly to shards over gRPC. Parameter ownership is:

```text
int.from_bytes(sha256(parameter_name.encode()).digest()[:8], "big") % shard_count
```

Shard index is the endpoint's position in the immutable configuration. Python's
randomized built-in hash is never used. Renaming a parameter or changing the
shard count can move ownership; live resharding is unsupported. Whole tensors
are assigned to shards, so load can be uneven and shards can be empty for very
small models. The two-shard MLP test asserts both shards own parameters.

The worker model performs forward and backward passes with PyTorch. Each shard
stores float32 NumPy weights and applies SGD itself. Plain SGD has no momentum
or Adam state; weights, version and replay receipts are authoritative. Supporting
a stateful optimizer will require including its state in checkpoints.

## Protocol and validation

Source: `proto/paramesh/rpc/training.proto`; package: `paramesh.v1`. Python bindings
and message `.pyi` files are generated and checked into source control. CI compares
fresh generation with committed bytes. New compatible fields can be added without
reusing existing field numbers. The wire version is early and not a stable public
API commitment yet.

Tensors carry a name, shape, explicit `float32-le` dtype and little-endian bytes.
The decoder allows at most eight dimensions, 4 MiB per tensor, 1,024 tensors and
8 MiB of tensor data per collection. RPC messages themselves are capped at 8 MiB,
including protobuf overhead. Scalars are allowed; zero-sized tensors are not.
Neither network endpoints nor model loading accept arbitrary Python object files.

Each update validates run identity, configured worker membership, exact parameter
names and shapes, dtype, payload length, finite values, update sequence and base
version. Decoding happens before entering the optimizer critical section. A
condition lock serializes commits. Proposed new weights are computed separately
and checked for overflow before replacing any authoritative weight.

## Versions, sequence numbers and retries

Each shard has its own monotonically increasing version, starting at zero.
Every accepted optimizer step increments it once, even for an empty shard. A
worker's update sequence starts at zero and increases by one per local iteration.
These are distinct counters: async shard versions count every worker's updates.

The shard remembers the latest accepted sequence, SHA-256 request fingerprint,
resulting version and staleness for each configured worker. An identical retry
returns that receipt without applying SGD again. A changed retry or sequence gap
is rejected. Memory is bounded by membership and one in-flight barrier. Older
receipts are not retained. Weights, SGD configuration, versions, receipts and fences
are committed together to SQLite WAL with `synchronous=FULL` before acknowledgement.
This supports retry after a process restart when the volume survives; it is not
an exactly-once delivery claim after storage loss.

Workers use explicit RPC deadlines and retry transient unavailable/deadline errors
at most three times with short backoff. They reuse the original request bytes;
they do not recompute a gradient after an ambiguous transport failure. Calls use
wait-for-ready within their deadlines so reconnection can outlast a transient
failure rather than exhausting retries immediately. A test
simulates losing the response after commit and verifies one update, not two.

## Synchronization

### Synchronous

Every worker submits one gradient per version. The shard accumulates a fixed
membership barrier, computes mean or sum and commits one SGD update. Float64
accumulation reduces summation overflow before conversion to float32 weights.
Mean gives equal weight to each worker, which is equivalent to the demo's local
reference because each worker has the same number of examples.

A shared deadline takes the earliest participant deadline, capped by the configured
barrier timeout. Late final arrivals cannot commit merely because an expired
waiting thread has not resumed yet. A timeout clears that shard's pending contributions and wakes waiting calls.
Membership is not silently reduced. The server's RPC thread limit exceeds the
configured worker count, preventing waiting participants from starving the final
arrival. No distributed commit ties separate shard barriers together.

### Asynchronous

Each valid gradient commits immediately. Staleness is `current_shard_version -
base_version` and is returned to the worker. Ordering depends on process and
network scheduling; async training is not expected to match synchronous SGD.

### Bounded lag

An update whose shard-local staleness exceeds `max_staleness` receives
`FAILED_PRECONDITION`. The worker pulls fresh weights and recomputes gradients
for contributions that have not yet committed in its current iteration. Already
accepted shards are not submitted again with changed contents. Refreshes are
bounded to 100 attempts; exhaustion fails the worker visibly.

Consequently a worker iteration can combine contributions computed from different
model snapshots. The bound is enforced at each shard's acceptance point. There is
no single global version, atomic multi-shard pull or classic SSP worker-clock bound.

## Failure and admission boundaries

Missing workers abort local synchronous barriers; membership is not silently
reduced. A worker journals complete gradient requests before sending them. After
restart it reads each shard's progress, skips completed contributions and finishes
the original pending step under its replacement generation. Fingerprints exclude
only generation metadata, so replacing a worker cannot change an already committed
gradient. Fresh bounded-mode recomputation only changes uncommitted contributions.

Shard restart reloads the last durable weights and receipts before serving traffic.
Tests actually terminate worker/shard processes and compare the completed sync run
with local SGD. State files have an OS-owned single-writer lock released on exit
or process death, preventing overlapping writers from corrupting worker journals.
Whole-run offline checkpoints preserve coordinator metadata, shard snapshots and
worker journals together. Export holds all source database leases; restore validates
every object before publishing fresh state. A partial multi-shard step retains its
original gradient bytes. Local and S3-compatible immutable stores publish manifests
last; an interrupted upload is not restorable. See [the recovery design](docs/recovery-design.md)
and [operator commands](docs/checkpoints.md). Live peers must never be mixed with
an older restored shard. Topology remapping and online coordinated cuts are unsupported.

gRPC admission is bounded to `2 * worker_count + 4` concurrent calls per shard;
excess requests receive resource exhaustion. Workers issue one gradient push at
a time. These limits do not replace deployment resource limits or provide a full
cluster-wide backpressure scheme. No unbounded training request queue is added.

## Deployment and evidence

The native demo spawns separate processes with OS-assigned loopback ports. It
waits for readiness, starts workers, collects final parameters and compares sync
weights against concatenated-data PyTorch SGD. Its control pipes are trusted,
local parent-child IPC, never the training transport.

Compose defines separate containers with an internal network, dropped capabilities,
read-only filesystems, five persistent volumes and no public training ports. Local
container verification checks actual training, role enforcement, clean shutdown
and state-preserving recreation. A large dependency download was completed in
validated ranges and matched PyTorch's published SHA-256; the local bootstrap
mirror did not change the installed package. Normal Git-backed builds use the
default official CPU index. No Coolify, k3s, AWS or Azure deployment has been exercised.

The optional SeaweedFS storage profile has a private network and a persistent volume.
The maintenance helper receives S3 credentials and can reach external endpoints;
training containers receive neither storage credentials nor a public route.
The optional operations profile adds a separate lifecycle event plane and telemetry
backends. NATS carries bounded allowlisted events, never gradient traffic. Broker
failure does not participate in registration, fencing, SGD or durable receipts.
Prometheus scrapes process/RPC metrics; OTel propagates gRPC trace context to Tempo.
The dashboard persists up to 200 validated events and mirrors them to Loki.
Its sampler uses read-only RPCs and fixed backend queries; its browser receives
neither data-plane nor administrative credentials. UI and Grafana publish loopback
ports through a management network, while internal networks keep training and
operations services private. See [operations](docs/operations.md) for definitions
and failure limits. Online checkpoint coordination, Azure and hosted validation follow.
