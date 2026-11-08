# PostgreSQL replication and promotion evidence

Captured on 2026-11-08 with `postgres:17-alpine` in two disposable Docker containers.

- Streaming state before failure: `streaming`
- Primary `pg_is_in_recovery()`: `f`
- Standby `pg_is_in_recovery()`: `t`
- Standby retained the pre-failover row: `1`
- Promoted standby `pg_is_in_recovery()`: `f`
- Rows after promotion: `2`
- Notes: `before-failover,after-promotion`
- Raw result SHA-256: `788d71987f07c652b3c51772441c960d5438ef190daca0fa83b02aeb9ef3a97c`

The harness removed its temporary containers, volumes, and network after the run. This is real
single-host PostgreSQL streaming-replication evidence, not a managed-cloud or production claim.
ParamMesh active-training failover remains open until coordinator replacement and worker/session
continuity are tested through the promoted database.
