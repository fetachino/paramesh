# Security model

ParamMesh currently supports trusted, local development clusters. Training gRPC
is plaintext and unauthenticated. Bind native services to loopback, or keep the
provided Compose network private. Do not expose these RPC ports to the internet
or untrusted tenants.

## Implemented boundaries

- Tensor messages use explicit float32 bytes, not pickle, `torch.load` or executable
  Python object serialization.
- Shape, dtype, byte length, parameter identity, finite values and collection sizes
  are validated before updates. Proposed optimizer results are validated before commit.
- RPCs have message and concurrent-request limits. The worker has finite retry and
  staleness-refresh budgets.
- Update run IDs, worker membership, sequence numbers and versions are checked.
- Control-plane session tokens are random, never written to demo reports and
  cannot be reused after their lease expires or a replacement registers.
- Container services run as UID 10001 with dropped capabilities, no published ports
  and an internal network. Container runtime behavior has not yet been verified locally.
- The repository ignores environment secrets and generated runtime artifacts.

## Limits

A configured worker ID is not a cryptographic identity. A local peer that can
reach a shard can impersonate an allowed worker, read weights or submit bounded
but malicious gradients. Finite gradients can still poison training. Coordinator
session fencing does not prevent that data-plane attack. Plaintext traffic can
be observed by other privileged processes on the host.

There is no TLS/mTLS, signed membership grant, multi-tenant isolation, dashboard
authentication, checkpoint deserialization path, object-storage credential manager
or OpenBao integration yet. These must be implemented and tested before expanding
the trust boundary. Rate and size limits reduce exposure but are not a memory
or CPU denial-of-service guarantee.

## Dependencies and verification

Direct dependencies are version-pinned. The local environment was audited using
pip-audit 2.10.1 against OSV after updating affected pins; the captured report is
under `docs/evidence/`. This is a point-in-time package advisory check, not a proof
of security. Reproducible transitive locking remains release work. An unavailable vulnerability
feed is not evidence of an absence of vulnerabilities. Generated protobuf code
is checked for drift; application source is linted, type-checked and exercised
with malformed-input, concurrent-retry and failure tests.

Do not put credentials, private datasets or sensitive paths in configuration,
training output, screenshots, benchmark reports or issue bodies. Use synthetic
data for portfolio evidence. Public security reports should omit exploitable
credentials or private data.
