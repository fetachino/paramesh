# Operations acceptance questions

1. Is training advancing, which worker/shard is unavailable, and how stale is each worker?
2. Is time spent in pulls, push/barrier waits, aggregation or durable optimizer commits?
3. Did a replacement/checkpoint actually complete, and can its event be traced to a run?
4. Does training remain correct when operational messaging or telemetry is unavailable?

Prometheus will expose finite-cardinality process/RPC and fixed-membership metrics.
Worker IDs are bounded by configured membership (64); run IDs, trace IDs, addresses
and error strings must not become metric labels. RPC bytes mean protobuf application
payload bytes, excluding HTTP/2 framing and TLS overhead. Histograms retain latency
distributions; no performance claim follows from a single correctness run.

OpenTelemetry gRPC instrumentation propagates context; manual spans cover training
and shard SGD commits. Exporters use bounded queues and private endpoints. Tokens,
raw request bodies, gradient values and TLS keys are excluded from spans and logs.

NATS carries allowlisted JSON lifecycle events only, never gradients. A bounded
nonblocking queue separates broker I/O from training. Delivery is best effort: outages
can drop events, counters expose loss, and events do not drive recovery decisions.
The coordinator/shard/worker databases remain authoritative. Structured service logs
provide local event evidence even when the broker is absent.

Compose remains the shared definition. Prometheus, Tempo, Loki, NATS and storage
stay private. Grafana is accessed through the dashboard/admin path, with persistent
credentials. Only the eventual dashboard/API receives a public Coolify route.
Public deployment remains pending server availability; no paid provisioning is authorized.

Verification must observe actual scraped series, a cross-service trace, events from a
real broker, and successful numerical training while the broker is unavailable.
Capture genuine UI evidence only after the corresponding backend queries succeed.
