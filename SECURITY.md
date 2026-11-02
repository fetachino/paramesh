# Security model

ParamMesh supports a trusted internal training group. CLI services require strong
service credentials. Native services bind to loopback by default; Compose keeps
gRPC on an internal network with no published ports. TLS/mTLS is available for
explicitly configured peers. The default private Compose bridge authenticates
RPCs but does not encrypt its traffic.

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
- Replacement registration durably advances a fencing generation on every shard.
  A stale worker cannot continue applying updates after the fence.
- Missing, invalid or duplicate authorization headers are rejected before protobuf
  decoding. A data credential cannot invoke administrative fencing operations.
- TLS/mTLS tests create temporary certificates and prove that a required client
  certificate is enforced; no reusable test private key is committed.
- ParamMesh training services run as UID 10001 with dropped capabilities, no published ports
  and an internal network. Local container verification exercises credential roles,
  private ports and persistent recreation.
- The repository ignores environment secrets and generated runtime artifacts.

## Limits

A configured worker ID is not an individual cryptographic identity. Workers with
the shared data credential belong to one trusted group and can impersonate other
configured members or submit finite but harmful gradients. Generation fencing
protects replacement ordering, not Byzantine behavior. There is no multi-tenant
isolation or per-node PKI. Host administrators can inspect local state and secrets;
plaintext private-bridge traffic can be observed by privileged host processes.

Signed per-node grants, managed object-storage secrets and OpenBao are not implemented.
Rate and size limits are not a memory/CPU denial-of-service
guarantee. Public proxy configuration must never route coordinator or shard gRPC.

## Credentials and transport configuration

Run `python scripts/create_dev_env.py` to create a private `.env` for Compose.
It uses distinct cryptographically random URL-safe values, never prints them and
never overwrites an existing file. `PARAMESH_RPC_TOKEN` is the data credential;
`PARAMESH_ADMIN_TOKEN` is only supplied to coordinator and shards. Rotate both by
updating the environment and recreating all services. Tokens are not stored in
checkpoint metadata or worker journals.

For native TLS, configure `PARAMESH_TLS_CA`, `PARAMESH_TLS_CERT` and
`PARAMESH_TLS_KEY` as PEM-file paths. `PARAMESH_REQUIRE_CLIENT_CERT=true` enables
mutual TLS on services. Operators must mount suitable certificates with matching
DNS names; no automatic CA, certificate rotation or composed PKI profile is claimed.
Workers only need the data token and their own client transport material.

The standalone demo generates ephemeral credentials internally. Library service
constructors permit omitted security for isolated tests; the CLI has no switch
for deploying unauthenticated services.

## Dependencies and verification

The optional dashboard authenticates one operator with a strong independent password
and expiring HMAC-signed HttpOnly/SameSite=Strict cookies. Restart or logout invalidates
sessions. POSTs reject cross-site/opaque origins; `Referrer-Policy: same-origin`
preserves a usable origin for normal same-site forms. Assets are local, CSP forbids
inline scripts/framing, HTTP bodies and thread counts are bounded, and routes are
allowlisted. The API is read-only. It holds a data credential internally but no admin
credential; browser responses omit service tokens. This is a small single-operator
console, without multi-user roles, MFA or an internet-facing rate-limit gateway.
Require HTTPS and `PARAMESH_COOKIE_SECURE=true` behind a public trusted proxy.

NATS requires its own shared group token. Prometheus, Tempo and Loki assume trusted
private networks; do not publish their ports or attach a public proxy. Grafana has
separate credentials and loopback-only access. NATS events and telemetry are best
effort, with bounded buffers; they are neither an audit log nor a recovery authority.
No tensors, secrets or user datasets are recorded in lifecycle events or spans.

Direct dependencies are version-pinned. The local environment was audited using
pip-audit 2.10.1 against OSV after updating affected pins; the captured report is
under `docs/evidence/`. This is a point-in-time package advisory check, not a proof
of security. Reproducible transitive locking remains release work. An unavailable vulnerability
feed is not evidence of an absence of vulnerabilities. Generated protobuf code
is checked for drift; application source is linted, type-checked and exercised
with malformed-input, concurrent-retry and failure tests.

Do not put credentials, private datasets or sensitive paths in configuration,
training output, screenshots, benchmark reports or issue bodies. Use synthetic
data for reproducible evidence. Public security reports should omit exploitable
credentials or private data.
