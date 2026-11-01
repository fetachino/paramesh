# Operator dashboard design contract

The screen answers whether the configured training run is advancing, where a failure
occurred, and which evidence supports recovery. Its primary action is inspection;
it must not mutate training, accept arbitrary RPCs, or expose service credentials.

The project has no existing visual design system. Use a compact engineering console:
dark slate surfaces, cyan for live signals, amber for pending/degraded state, readable
monospace identifiers, thin dividers and small consistent radii. The provisioned
Grafana operations view supplies query/legend conventions. A topology and membership
table take priority over decorative cards. Avoid marketing copy, gradients and
unlabeled status colors.

Navigation: overview, workers, recovery/checkpoints, traces and captured correctness
runs. Live values come from authenticated coordinator/shard RPCs and Prometheus.
Lifecycle history comes from validated NATS events and persists locally; publication
is best effort, so show connection status and label checkpoint history as observed.
Historical benchmark/fault reports must retain their own source/time/workload context.
Missing or stale measurements must remain unknown, rather than becoming zero or healthy.

Use semantic HTML, keyboard-accessible controls, visible focus, table headers,
text status labels and accessible SVG plots. At 320px use one column and horizontally
scrollable tables; expand at 768/1024/1440px without clipping. Provide loading, empty,
unavailable and authentication states. Serve all assets locally with a restrictive CSP.

Verify in a dedicated browser surface, inspect console/network/accessibility output,
and capture actual running state. No sample metric may be substituted into a live
view to make a screenshot look complete.
