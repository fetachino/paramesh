# Contributing to ParamMesh

Thanks for your interest in ParamMesh. Bug reports, reproducible experiments, documentation corrections, tests, and focused code improvements are welcome.

ParamMesh is still under active development. The bundled workload currently targets CPU float32 PyTorch training with a fixed model and topology. Do not assume arbitrary user models, managed cloud durability, production availability, or a completed v1.0 release.

## Before starting

- Read [README.md](README.md), [ROADMAP.md](ROADMAP.md), and [SECURITY.md](SECURITY.md).
- Search existing issues and pull requests for overlapping work.
- For substantial architectural changes, open an issue describing the problem, alternatives, and intended scope before implementing.
- Do not publish credentials, private endpoint details, sensitive logs, or real user data. Report vulnerabilities privately using the process in [SECURITY.md](SECURITY.md), not public issues.

## Development workflow

1. Fork or branch from the current `main`.
2. Follow the repository's existing Python environment, lockfile, generated-protocol, and test instructions in the README and CI workflows; do not introduce an unrelated build system.
3. Keep changes small and focused. Include tests for behavioral changes and update docs when behavior or operational requirements change.
4. Run the relevant quality, unit, and container checks documented in the repository. Explain any checks you could not run.
5. Open a pull request using the template, linking the relevant issue and including evidence and limitations.

## Engineering expectations

- Preserve backward compatibility and durable state semantics unless an intentional migration is documented and tested.
- Treat synchronization, checkpointing, fencing, authentication, and retry changes as correctness-sensitive; include failure-path and replay tests.
- Keep public ports, credentials, and operational security boundaries unchanged unless the change is explicitly reviewed.
- Do not edit or recreate live infrastructure, named volumes, or production data as part of an ordinary contribution.
- Never claim performance or recovery guarantees without reproducible measurements, configuration, and source identity.
- Do not commit generated secrets, local state, large unreviewed binaries, or fabricated benchmark results.

Contributions are submitted under the repository's [Apache License 2.0](LICENSE). By submitting a contribution, you agree that it may be distributed under that license.
