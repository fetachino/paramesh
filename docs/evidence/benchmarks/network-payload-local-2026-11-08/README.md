# Network and payload measurement

This sanitized evidence records three repetitions of sync, async, and bounded-staleness runs with the uncompressed transport.

- Source: `07a40ac1e78679ca5fedeaf7ee248f82e0e3d5f8`
- Configuration: 2 workers, 2 shards, 20 warm-up steps, 100 measured steps, 3 repetitions per mode
- Result: 9/9 trials completed with zero RPC failures; sync max parameter error was `0.0`
- Observed sync payload: about 84.5 KiB total protobuf bytes per trial, push request mean 71.5 bytes, pull request mean 19 bytes, push p95 below 4.6 ms on this host

The measurements do not show a network bottleneck for this small CPU workload. Compression remains deferred until larger payloads or real network measurements justify its complexity. Host load was uncontrolled; this is not a general performance ranking.
