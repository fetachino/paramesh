# Clean-source eight-worker scaling matrix

This capture was produced from merged ParamMesh commit
`cf2a295ac34ad70184bd50af5c8d94417b31fac2` with `source_dirty=false` and the
checked-in lockfile. It measures the synchronous process harness against the
single-process PyTorch reference for three repetitions at 1, 2, 4, and 8
workers.

Host: Windows 11 AMD64, 13th Gen Intel Core i7-13700F, 24 logical CPUs,
34,055,766,016 bytes of reported memory, Python 3.12.10. Each trial used 20
warm-up steps, 200 measured steps, two shards, the seeded bundled MLP workload,
and no network isolation. Background services were uncontrolled.

| Workers | ParamMesh median examples/s (range) | Reference median examples/s (range) | Worst parameter error |
| ---: | ---: | ---: | ---: |
| 1 | 1,051.23 (883.44–1,065.87) | 99,906.81 (91,563.96–101,344.88) | 4.77e-7 |
| 2 | 1,909.94 (1,764.18–2,022.00) | 189,255.32 (184,779.38–200,721.97) | 4.77e-7 |
| 4 | 3,510.52 (3,450.53–3,645.27) | 401,230.65 (395,175.16–405,221.02) | 7.15e-7 |
| 8 | 5,890.08 (5,794.58–6,162.88) | 725,198.08 (631,114.69–775,221.97) | 7.15e-7 |

All twelve ParamMesh trials completed without a recorded failure. Every trial
matched the deterministic reference within the existing `1e-6` correctness
gate. These values describe this workload and uncontrolled workstation only;
they are not a universal speedup claim, a multi-host result, a network
bandwidth measurement, or a production capacity guarantee. Startup,
registration, fencing, and final heartbeat are inside the ParamMesh timing
boundary, while the reference is single-process.

The 8-worker run extends the local scaling baseline but does not close the
multi-host performance limitation. A separate Linux-host measurement must use
the documented private-network deployment path and preserve the same raw
configuration, lock hash, hardware metadata, and failure records.

The raw manifest, all ParamMesh/reference JSON records, CSV summary, charts,
lockfile snapshot, and checksums are preserved here. The records contain no
credentials, tokens, private endpoints, tensors, or customer data.

Reproduce the same configuration with:

```powershell
uv run --locked --extra train --extra benchmark python examples/scaling_matrix.py `
  --output artifacts/scaling-matrix `
  --workers 1 2 4 8 `
  --repetitions 3 `
  --warmup-steps 20 `
  --steps 200
```
