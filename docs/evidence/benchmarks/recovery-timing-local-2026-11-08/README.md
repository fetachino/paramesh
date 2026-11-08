# Repeated process fault timing

This evidence uses the existing recovery harness with three repetitions each of worker and shard termination (six trials total).

- Source: `07a40ac1e78679ca5fedeaf7ee248f82e0e3d5f8`
- Configuration: synchronous mode, 2 workers, 2 shards, 20 steps, 0.1 s step delay
- Result: 6/6 trials recovered, equal shard versions, and max parameter error below `6e-8`
- Detection/recovery timings are raw observations in `trials.csv`; they are not an availability or latency SLA

The run validates repeated local fault handling. It does not prove multi-host fault timing, coordinator HA, or production performance.
