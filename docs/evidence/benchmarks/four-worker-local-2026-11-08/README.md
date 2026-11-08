# Four-worker repeated local measurement

This sanitized evidence records three repeated four-worker synchronous runs of the existing process harness. It is a controlled workstation measurement, not a multi-host performance claim.

- Source: `07a40ac1e78679ca5fedeaf7ee248f82e0e3d5f8`
- Configuration: 4 workers, 2 shards, 20 warm-up steps, 100 measured steps, 3 repetitions
- Result: all 3 runs completed; max parameter error `4.76837158203125e-07`; shard commits were equal
- Host: Windows 11, AMD64, 24 logical CPUs, Intel i7-13700F; background load was uncontrolled

Raw JSON, CSV, charts, and checksums are kept beside this file. These results establish repeatability for the local harness only; they do not establish WAN scaling, compression benefit, HA, GPU support, or an SLA.
