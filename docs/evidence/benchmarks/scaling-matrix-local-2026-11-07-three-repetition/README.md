# Clean-source three-repetition scaling matrix

This capture was produced from merged ParamMesh commit
`38074fb6c3b2d45fc426608e4c6f16d8ed3b35d7` with `source_dirty=false` and the
checked-in lockfile. It measures the synchronous process harness against the
single-process PyTorch reference for three repetitions at 1, 2, and 4 workers.

Host: Windows 11 AMD64, 13th Gen Intel Core i7-13700F, 24 logical CPUs,
34,055,766,016 bytes of reported memory, Python 3.12.10. Each trial used 20
warm-up steps, 200 measured steps, two shards, the seeded bundled MLP workload,
and no network isolation. Background services were uncontrolled.

| Workers | ParamMesh median examples/s (range) | Reference median examples/s (range) | Worst parameter error |
| ---: | ---: | ---: | ---: |
| 1 | 843.19 (835.33–844.42) | 75,320.44 (58,585.26–75,340.39) | 4.77e-7 |
| 2 | 1,616.22 (1,601.09–1,623.74) | 148,153.64 (144,691.63–148,438.50) | 4.77e-7 |
| 4 | 2,930.15 (2,852.41–2,963.27) | 277,752.16 (276,615.01–284,325.66) | 7.15e-7 |

All nine ParamMesh trials completed without a recorded failure. Every trial
matched the deterministic reference within the existing `1e-6` correctness
gate. These values describe this workload and uncontrolled workstation only;
they are not a universal speedup claim, a multi-host result, or a production
capacity guarantee. Startup, registration, fencing, and final heartbeat are
inside the ParamMesh timing boundary, while the reference is single-process.

The raw manifest, all ParamMesh/reference JSON records, CSV summary, chart, and
exact lockfile snapshot are preserved here. `SHA256SUMS` covers every file.
The records contain no credentials, tokens, private endpoints, tensors, or
customer data.

Reproduce the same configuration with:

```powershell
uv run --locked --extra train --extra benchmark python examples/scaling_matrix.py `
  --output artifacts/scaling-matrix `
  --workers 1 2 4 `
  --repetitions 3 `
  --warmup-steps 20 `
  --steps 200
```
