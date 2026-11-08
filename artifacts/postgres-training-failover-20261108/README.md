# PostgreSQL failover during active training

This disposable local run uses PostgreSQL 17 primary/standby containers, promotes
the standby, and keeps two ParamMesh workers training against the replacement
coordinator. Credentials and container identifiers are generated at runtime and
are not stored in this directory.

## Result

The run reached the promoted coordinator and both workers continued to their
configured target. Both workers re-registered at generation 2, reached healthy
checkpoint-safe leases, and published checkpoint `ha-after-failover` at global
step 8 with matching shard versions `[8, 8]`. Both then completed step 80 with
matching final shard versions `[80, 80]`.

The raw sanitized result is in `results.json`; the source/test configuration is
the checked-in verifier. No production services,
volumes, credentials, or cloud resources were used.

## Reproduce

```powershell
uv run python scripts/verify_postgres_training_failover.py `
  --output artifacts/postgres-training-failover-20261108/results.json
```

The verifier removes its temporary Docker network, containers, and volumes in a
`finally` block. This closes local active-training coordinator/database failover
evidence for the disposable single-host topology. It does not claim replicated
production PostgreSQL HA or cross-host availability.
