# ParamMesh

A parameter-server training system under development. The intended architecture
separates coordinator membership from worker-to-shard gradient traffic and keeps
distributed-training logic in this repository.

## Current status

The foundation includes a Python 3.12 package, generated v1 gRPC/Protocol Buffers
contracts, deterministic parameter ownership, bounded float32 tensor encoding,
unit tests and a CI workflow. Training services are the next implementation slice.
See [the implementation plan](tasks/plan.md). No deployment, performance or
fault-tolerance claim is made for this initial foundation.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
python scripts/generate_proto.py --check
```

On Linux, activate with `source .venv/bin/activate`. Regenerate protocol bindings
with `python scripts/generate_proto.py` after editing the `.proto` contract.

## Design constraints

- Typed gRPC messages carry canonical little-endian float32 bytes; no network pickle.
- SHA-256 of the parameter name determines shard ownership for a fixed shard count.
- Infrastructure and dashboards follow a tested core; optional tools must solve
  an actual operational need.
- Benchmarks and screenshots must come from genuine, reproducible runs.
