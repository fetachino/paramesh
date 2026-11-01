# Interview guide

## Short explanation

ParamMesh separates PyTorch gradient computation from authoritative parameter
storage. Independent workers use a repository-owned gRPC protocol to train against
shards that validate updates, aggregate gradients and apply SGD. The coordinator
tracks membership and heartbeat leases. Synchronous correctness is checked against
equivalent local training. Durable recovery is the next major milestone.

## Two-minute walkthrough

Start with `paramesh demo`: the parent launches a coordinator, two shards and two
workers as independent processes. Each worker gets a fixed data partition, pulls
the model, runs autograd and sends gradients to their owning shards. A stable hash
maps parameter names to an immutable ordered shard map. The shard owns SGD and
the parameter version, not the worker.

In sync mode, every configured worker contributes to each local barrier. With
equal-sized batches, mean aggregation matches SGD over the concatenated dataset.
The test compares actual final weights, not only decreasing loss. Async mode
commits contributions immediately; bounded mode rejects updates whose referenced
shard version is too old. Neither mode promises identical convergence to sync.

Retries are important: a transport deadline can occur after commit. A shard's
latest worker-step fingerprint returns the original receipt instead of applying
the update twice. That guarantee ends at process restart because receipts are
currently in memory. Multi-shard commits are also not atomic. Explaining those
limits is part of the design, not a claim that fault tolerance is complete.

## Questions to prepare

1. **Why a parameter server rather than all-reduce?** It makes centralized optimizer
   ownership, parameter partitions and independent worker progress explicit. It also
   introduces shard bottlenecks and consistency questions. No all-reduce comparison
   has been measured here.
2. **What is repository-owned?** The protocol, membership, validation, sharding,
   aggregation, versions, receipts, barriers, worker loop and demo verification.
3. **What does PyTorch do?** Forward/backward computation and the local SGD reference.
   It does not provide the distributed synchronization layer.
4. **How is sharding reproducible?** SHA-256 of a name modulo the immutable shard count.
5. **Can ownership be unbalanced?** Yes. Whole-tensor hashing does not balance bytes;
   a small model may leave shards empty. Resharding needs a separate migration protocol.
6. **Who owns optimizer state?** Shards own weights and SGD updates. Momentum and Adam
   are not implemented. Their extra state would have to be checkpointed.
7. **Why compare weights instead of loss alone?** Loss can decrease despite aggregation
   bugs. Equivalent initialization, batches and steps make a numerical oracle possible.
8. **When is mean aggregation equivalent to full-batch SGD?** When worker batches have
   equal sample counts and use the same mean-reduced objective, as in this workload.
9. **What if one sync worker disappears?** The local barrier times out and clears pending
   gradients. Membership does not silently shrink and training does not auto-recover.
10. **What is a parameter version?** A per-shard count of committed optimizer updates,
    distinct from each worker's local iteration count.
11. **What is staleness?** The current shard version minus the worker's base version.
12. **Is bounded mode classic SSP?** No. It bounds accepted gradient lag per shard;
    it does not bound global worker clocks or provide a consistent multi-shard snapshot.
13. **What happens after a partial multi-shard push?** Already accepted contributions
    are retained. Bounded refresh only resubmits uncommitted shards. A process failure
    can leave partial state requiring future coordinated recovery.
14. **What if the response is lost after commit?** The client retries the same request.
    The current process's receipt prevents another update for that worker step.
15. **Why not keep every receipt?** Latest-only receipts bound memory and match the
    worker's sequential push behavior. Arbitrarily old retries are rejected.
16. **Does a coordinator lease secure gradients?** No. Session fencing applies to
    heartbeat identity; shards still trust configured worker IDs on a private network.
17. **How are bad payloads handled?** Explicit dtype/shape/length/identity/size checks,
    finite gradients and finite proposed optimizer results precede commit.
18. **What provides backpressure?** Bounded gRPC admission, message limits and one
    sequential worker push. Full queue metrics and adaptive pacing remain future work.
19. **What is required for a valid checkpoint?** A coordinated epoch/quiescence boundary,
    durable per-shard weights/optimizer state/receipts, checksums and an atomic manifest.
    Independently saving live shards would not establish a consistent training snapshot.
20. **How would storage portability work?** Put checkpoint blobs/manifests behind a
    tested store contract; exercise S3 operations on SeaweedFS and Azure SDK operations
    on Azurite before claiming compatibility. Neither adapter exists yet.
21. **Where would NATS fit?** Optional lifecycle events, outside the gradient path.
    Training correctness should not require the event broker.
22. **What observability is implemented?** JSON command output, status RPCs and run
    artifacts. Prometheus, OpenTelemetry, Grafana, Tempo and Loki are not integrated yet.
23. **What does Compose prove?** The repository defines separate-container topology and
    validates syntax. A workflow definition alone does not prove containers ran.
24. **How would production identity differ?** TLS/mTLS or verifiable service grants for
    RPCs; a separate OIDC provider for a future browser dashboard. Keycloak/OpenBao
    should not be confused with current implementations.
25. **What are the deployment limits?** Native tests are one-host CPU runs. Coolify,
    k3s, OpenTofu and managed AWS/Azure deployments have not been exercised.
26. **What is the next engineering risk to resolve?** Coordinated recovery and fencing
    after partial multi-shard commits, before claiming fault tolerance or adding a large UI.
