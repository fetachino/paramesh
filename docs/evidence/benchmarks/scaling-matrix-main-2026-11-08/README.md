# Clean-source eight-worker scaling matrix

This capture was produced from merged ParamMesh commit
`8605ccd45c8201a16f47cfa9b82ae9f86fdbcd36` with `source_dirty=false` and the
checked-in lockfile. It measures the synchronous process harness against a
single-process PyTorch reference for three repetitions at 1, 2, 4, and 8
workers.

Host: Windows 11 AMD64, 13th Gen Intel Core i7-13700F, 24 logical CPUs,
34,055,766,016 bytes of reported memory, Python 3.12.10. Each trial used 5
warm-up steps, 50 measured steps, two shards, the seeded bundled MLP workload,
and no network isolation. Background services were uncontrolled.

| Workers | ParamMesh median examples/s (range) | Worst parameter error |
| ---: | ---: | ---: |
| 1 | 352.32 (340.69–368.59) | 2.38e-7 |
| 2 | 689.25 (687.48–703.30) | 1.19e-7 |
| 4 | 1,316.12 (1,309.96–1,316.28) | 2.38e-7 |
| 8 | 2,319.88 (2,318.49–2,404.81) | 2.38e-7 |

All 12 ParamMesh trials completed without a recorded failure, and every trial
matched the deterministic reference within the existing `1e-6` correctness
gate. These values describe this workload and uncontrolled workstation only;
they are not a universal speedup claim, a WAN result, a compression decision,
or a production capacity guarantee. Startup, registration, fencing, and final
heartbeat are inside the ParamMesh timing boundary, while the reference is
single-process.

The raw manifest, all ParamMesh/reference JSON records, CSV summary, and charts
are preserved here. The manifest records the lockfile SHA-256. `SHA256SUMS`
covers every artifact. The records contain no credentials, tokens, private
endpoints, tensors, or customer data.

Reproduce the same configuration with:

```powershell
uv run --locked --extra train --extra benchmark python examples/scaling_matrix.py `
  --output artifacts/scaling-matrix `
  --workers 1 2 4 8 `
  --repetitions 3 `
  --warmup-steps 5 `
  --steps 50
```

