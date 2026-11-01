# ParamMesh

A distributed parameter-server training core with independently running PyTorch
workers, a membership coordinator and sharded authoritative model state. The
repository owns the gRPC protocol, gradient validation, SGD updates, versioning,
replay protection and synchronization behavior.

**Status: early implementation.** CPU training is exercised across independent
processes on one host. Synchronous runs are checked against equivalent local
PyTorch SGD. Checkpointing, restart recovery, dashboards and cloud deployments
are future work; this is not yet a fault-tolerant training platform.

[Architecture](ARCHITECTURE.md) · [Evidence and methodology](BENCHMARKS.md) ·
[Security boundaries](SECURITY.md) · [Roadmap](ROADMAP.md)

## What this proves

- Control-plane membership is separate from worker-to-shard gradient traffic.
- Typed network boundaries reject malformed tensors and inconsistent updates.
- Concurrent workers synchronize through explicit shard-local gradient barriers.
- Ambiguous RPC delivery is handled by retrying identical requests without a
  second optimizer update while the shard process remains alive.
- Synchronous numerical correctness is compared with a real autograd baseline.

## Why this project exists

Parameter servers make optimizer ownership, stale gradients, membership and
failure boundaries explicit. A small CPU model keeps the focus on those systems
decisions. No Ray Train, DDP, Horovod or other distributed trainer implements the
protocol underneath this project.

## Run the distributed demo

Requires Python 3.12 on an x86-64 machine. The verified local environment is Windows;
Linux verification is configured in CI but has not been run locally.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[dev,train]"
paramesh demo --mode sync --workers 2 --shards 2 --steps 20 --output artifacts/sync.json
```

On Linux, activate with `source .venv/bin/activate`. The demo starts **five child
processes**: one coordinator, two parameter shards and two workers. Actual gRPC
calls carry model parameters and gradients; local process pipes only carry
startup addresses, stop signals and demo results. All child processes are cleaned
up when the command finishes.

The workload is a seeded 4 → 8 → 1 MLP with tanh, 32 synthetic regression examples
per worker and shard-owned SGD. The JSON output records loss, shard versions,
parameter ownership, worker completion, source provenance and the synchronous
reference error. This command is a correctness demonstration, not a scaling benchmark.

[Captured run evidence](docs/evidence/README.md) records 41 passing tests and 93.39%
statement coverage. The 20-step sync run reduced full-dataset MSE from 14.232687
to 0.733824 with maximum absolute parameter error `5.96e-8` versus local SGD.

```powershell
paramesh demo --mode async --output artifacts/async.json
paramesh demo --mode bounded --output artifacts/bounded.json
```

## Core capabilities

| Area | Working behavior |
| --- | --- |
| Transport | Generated `paramesh.v1` gRPC contracts, deadlines, 8 MiB RPC limit |
| Membership | Configured worker IDs, session leases, suspect/unavailable thresholds, completion |
| Ownership | Stable SHA-256 parameter-name hashing for an immutable shard count |
| Validation | Run, worker, sequence, version, identity, shape, dtype, byte length and finite values |
| SGD | Shard-local authoritative weights; mean or sum aggregation in synchronous mode |
| Synchronous | Fixed membership, one contribution per worker, barrier timeout without a local commit |
| Asynchronous | Atomic local updates with reported shard-local staleness |
| Bounded | Reject excessive shard-local lag; refresh and recompute uncommitted contributions |
| Delivery | Latest accepted worker-step receipt prevents duplicate application within a shard lifetime |
| Admission | Bounded concurrent RPCs and bounded tensor collections |

## Architecture and training flow

```mermaid
flowchart TB
    C[Coordinator: run configuration and worker leases]
    W0[Worker 0: PyTorch forward and backward]
    W1[Worker 1: PyTorch forward and backward]
    S0[Shard 0: weights, SGD, version and receipts]
    S1[Shard 1: weights, SGD, version and receipts]
    W0 -. registration and heartbeat .-> C
    W1 -. registration and heartbeat .-> C
    C -. configuration and shard endpoints .-> W0
    C -. configuration and shard endpoints .-> W1
    W0 <-->|gRPC pull / push| S0
    W0 <-->|gRPC pull / push| S1
    W1 <-->|gRPC pull / push| S0
    W1 <-->|gRPC pull / push| S1
```

Workers register, pull parameters, compute a real forward/backward pass, partition
gradients by parameter name, submit each shard's contribution and repeat. Workers
do not own an optimizer. See [ARCHITECTURE.md](ARCHITECTURE.md) for exact semantics.

## Synchronization and failure boundaries

Synchronous mode requires every configured worker at each shard. A missing worker
aborts that shard's pending barrier rather than silently shrinking participation.
Async mode permits older gradients; bounded mode enforces `max_staleness` against
each shard's current version. Mean aggregation assumes equal worker batch sizes.

**There is no cross-shard transaction.** A failure can leave an update committed
on one shard and pending on another. Async and bounded pulls can observe different
shard versions; bounded mode does not provide a globally consistent model snapshot
or classic SSP worker-clock guarantees. Coordinated recovery is the next major
correctness workstream.

## Start components independently

Run each command in a separate terminal, with the environment activated:

```powershell
paramesh coordinator --config examples/local.json
paramesh shard --config examples/local.json --index 0
paramesh shard --config examples/local.json --index 1
paramesh worker --coordinator 127.0.0.1:50050 --id worker-0 --steps 20
paramesh worker --coordinator 127.0.0.1:50050 --id worker-1 --steps 20
```

Inspect membership with `paramesh status`. Shut down all components and start a
fresh run before repeating this fixed-identity workload. Reusing a completed
worker ID against existing shard sequence state is not a supported resume flow.

## Containers

```powershell
docker compose up --build -d
docker compose logs -f worker-0 worker-1
docker compose exec coordinator paramesh status --coordinator coordinator:50050
docker compose down
```

Compose defines five separate containers, health checks, non-root execution and
an internal network with no published ports. Workers complete 20 steps and exit.
Restarting a shard loses its in-memory state. Compose syntax is locally validated.
The Docker engine was started, but image building was blocked by interrupted CPU
PyTorch wheel downloads from both official endpoints; container execution remains
unverified. The configured
CI container job checks that both workers exit successfully. No passing CI or
deployment claim is implied by a workflow file.

## Verification and testing

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python scripts/generate_proto.py --check
python -m pytest --cov --cov-report=term-missing --cov-report=xml
python -m build
docker compose config --quiet
```

Tests cover real gRPC round trips, concurrent retry delivery, missing barrier
participants, optimizer overflow, lease expiry, old-session rejection and all
three training modes. Spawned-process coverage is enabled. Generated code and the
CLI dispatcher are excluded from coverage; application logic is included.

## Repository structure

```text
proto/paramesh/rpc/       Versioned source protocol
src/paramesh/            Coordinator, shards, workers, workload, CLI and demo harness
src/paramesh/rpc/        Generated Python bindings and message type stubs
tests/                  Unit, network integration and independent-process tests
examples/               Local and container run configurations
tasks/                  Implementation plan
docs/                   Interview notes and genuine run evidence
```

## Current limitations and next work

No durable checkpoints, coordinator persistence, shard recovery, automatic worker
rejoin, TLS, data-plane authentication, metrics backend, dashboard, compression,
object storage or validated multi-machine deployment exists yet. The protocol is
float32-only and the executable workload is deliberately fixed and CPU-only.

The cloud-portability goal is to add storage adapters for SeaweedFS/S3 and
Azurite/Azure Blob, then optional NATS events, observability and self-hosted
deployment. Those integrations must earn their place through tests and evidence;
they are not current capabilities. See [ROADMAP.md](ROADMAP.md).

## Additional documentation

- [Implementation plan](tasks/plan.md)
- [Architecture and consistency model](ARCHITECTURE.md)
- [Correctness evidence and benchmark policy](BENCHMARKS.md)
- [Security model](SECURITY.md)
- [Interview guide](docs/interview-guide.md)
- [Resume notes](docs/resume-notes.md)
