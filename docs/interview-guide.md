# Interview guide

## Short explanation

ParamMesh separates PyTorch gradient computation from authoritative parameter
storage. Independent workers use a repository-owned gRPC protocol to train against
shards that validate updates, aggregate gradients and apply SGD. The coordinator
tracks membership and heartbeat leases. Synchronous correctness is checked against
equivalent local training, including actual worker and shard process recovery
when durable local volumes survive.

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
the update twice. Receipts and weights are committed together before acknowledgement.
Workers journal gradients before delivery so a replacement can finish a partial
step without changing its numerical meaning. Multi-shard commits remain non-atomic;
retained-volume process recovery does not imply recovery after disk loss.

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
   gradients. Membership does not silently shrink. A replacement waits for lease
   expiry, advances its fencing generation and resumes its durable gradient journal.
10. **What is a parameter version?** A per-shard count of committed optimizer updates,
    distinct from each worker's local iteration count.
11. **What is staleness?** The current shard version minus the worker's base version.
12. **Is bounded mode classic SSP?** No. It bounds accepted gradient lag per shard;
    it does not bound global worker clocks or provide a consistent multi-shard snapshot.
13. **What happens after a partial multi-shard push?** Already accepted contributions
    are retained. Bounded refresh only resubmits uncommitted shards. A process failure
    resumes the original unfinished request set from its write-ahead journal.
14. **What if the response is lost after commit?** The client retries the same request.
    The durable receipt prevents another update for that worker step after a restart.
15. **Why not keep every receipt?** Latest-only receipts bound memory and match the
    worker's sequential push behavior. Arbitrarily old retries are rejected.
16. **Does a coordinator lease secure gradients?** Generation fencing rejects old
    incarnations at shards, while service credentials authenticate the internal group.
    Shared credentials do not establish individual identities or Byzantine safety.
17. **How are bad payloads handled?** Explicit dtype/shape/length/identity/size checks,
    finite gradients and finite proposed optimizer results precede commit.
18. **What provides backpressure?** Bounded gRPC admission, message limits and one
    sequential worker push. Actual in-flight, barrier and event-queue metrics are exposed;
    adaptive training admission remains future work.
19. **What is required for a valid checkpoint?** Stop every role, hold all state leases,
    validate weights/optimizer configuration/receipts/journals and publish a checksummed manifest last.
    Independently saving live shards would not establish a consistent training snapshot.
20. **How would storage portability work?** Put checkpoint blobs/manifests behind a
    tested store contract; exercise S3 operations on SeaweedFS and Azure SDK operations
    on Azurite before claiming compatibility. Local/S3 stores and actual SeaweedFS tests
    are implemented; Azure follows.
21. **Where does NATS fit?** Optional allowlisted lifecycle events, outside the gradient
    path. Actual outage/full-queue tests prove numerical training remains independent.
22. **What observability is implemented?** Real Prometheus metrics, provisioned Grafana,
    OTel step/RPC/SGD spans in Tempo and validated lifecycle logs mirrored to Loki.
    The read-only dashboard uses authenticated RPCs and fixed backend queries.
23. **What does Compose prove?** The black-box verifier trains in separate containers,
    checks data/admin credentials and private ports, then recreates the cluster and
    verifies durable resume. Core CI and local runtime runs have passed.
24. **How would production identity differ?** TLS/mTLS transport is tested, but per-node
    certificate issuance/rotation and browser OIDC are separate work. Keycloak/OpenBao
    are not current implementations.
25. **What are the deployment limits?** Native tests are one-host CPU runs. Coolify,
    k3s, OpenTofu and managed AWS/Azure deployments have not been exercised.
26. **What is the next engineering risk to resolve?** Azure checkpoint portability and
    controlled uncompressed performance/failure baselines. A real server is required
    to verify the prepared Git-backed Coolify route; no free compute is assumed.
