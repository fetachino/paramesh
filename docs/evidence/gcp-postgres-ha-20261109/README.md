# Google Cloud PostgreSQL HA validation

This record captures an isolated, real-VM validation of PostgreSQL-backed
coordinator fencing and active-training failover. It did not modify the
ParamMesh production VM, Coolify, HTTPS routing, credentials, or production
volumes.

## Source and environment

- Source SHA: `9dc3694eae30b9a4c8b3811408f6f979e62a7c0f`
- Project: Google Cloud trial project (private project identifier omitted)
- Hosts: two private `e2-medium` VMs on the ParamMesh VPC
- Database: PostgreSQL 16 streaming replication, primary and standby
- Public database exposure: none; administration used IAP

## Active-training failover result

The run started two synchronous workers at generation 1, stopped the
coordinator and primary PostgreSQL process, promoted the standby, and started
a replacement coordinator against the promoted database. Workers reconnected
without process restarts.

- Pre-failover worker state: both workers healthy at step 3, generation 1
- First post-failover healthy state: both workers generation 2
- Post-failover checkpoint: `gcp-ha-after-failover`
- Checkpoint global step: `33`
- Checkpoint shard versions: `33`, `33`
- Final worker state: both workers completed step `100`, generation 2
- Worker result messages: `2`; worker errors: `0`
- Durable state and fencing checks: passed

The raw JSON result, local shard state, checkpoint directory, and checksum are
preserved outside Git in the protected operator evidence store. Raw result
SHA-256:

`83920fbd4dc88b70ab27b74e605c890873846b0bfaf879a48dfe980bc90c9cc4`

## Validation checks

- PostgreSQL-backed fencing tests: `3 passed`
- Coordinator/coordinator unit checks: `11 passed, 2 skipped` (the two skipped
  cases require an explicitly supplied DSN)
- Ruff: passed
- mypy: passed (`26 source files`)
- Docker image build with pinned base images: passed

## Scope and limitations

This closes the isolated real-GCP active-training failover evidence for the
two-node PostgreSQL pair. It does not claim that ParamMesh production has been
migrated to PostgreSQL, that PostgreSQL has automatic orchestration or quorum
consensus, or that the topology provides zero-downtime/high-availability
guarantees. Production migration remains a separate, explicitly approved
operation.
