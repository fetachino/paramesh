# Clean-source scaling matrix smoke run

This capture was produced from merged ParamMesh commit
`b5b55c52e58c8b83c062a725b0f83081e3387634` with `source_dirty=false` and the
checked-in lockfile. It is a reproducible smoke matrix, not a performance
ranking: one repetition, two warm-up steps, six measured steps, two shards, and
an uncontrolled Windows workstation.

Host: Windows 11 AMD64, 13th Gen Intel Core i7-13700F, 24 logical CPUs,
34,055,766,016 bytes of reported memory, Python 3.12.10. The retained local
operations stack and ordinary background services were not treated as an
isolated benchmark environment.

| Workers | ParamMesh examples/s | PyTorch reference examples/s | ParamMesh final loss | Max parameter error |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 41.8521 | 80,679.0485 | 2.3293211460 | 5.96e-8 |
| 2 | 90.2133 | 140,995.0431 | 2.6959614754 | 8.94e-8 |
| 4 | 159.7976 | 276,388.2391 | 2.4003067017 | 5.96e-8 |

The reference is a deterministic single-process PyTorch SGD run using the same
workload factory, optimizer, steps, and worker batches. The small error values
are correctness checks; they do not imply equal throughput or model-quality
comparability beyond this workload.

The raw manifest, per-trial ParamMesh and reference JSON, CSV summary, chart,
and exact `uv.lock` snapshot are in this directory. `SHA256SUMS` covers every
captured file. No credentials, tokens, endpoints, tensors, or private runtime
state are included.

To reproduce the same shape of run from a fresh checkout:

```powershell
uv run --locked --extra train --extra benchmark python examples/scaling_matrix.py `
  --output artifacts/scaling-matrix `
  --workers 1 2 4 `
  --repetitions 1 `
  --warmup-steps 2 `
  --steps 6
```

The documented release-quality comparison remains the three-repetition run in
`BENCHMARKS.md`; this smaller capture proves that the merged runner produces a
complete raw 1/2/4 matrix from a clean source tree.
