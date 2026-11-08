# PostgreSQL failover during active training

This disposable local run uses PostgreSQL 17 primary/standby containers, promotes
the standby, and keeps two ParamMesh workers training against the replacement
coordinator. Credentials and container identifiers are generated at runtime and
are not stored in this directory.

## Result

The run reached the promoted coordinator and both workers continued to their
configured target. The post-promotion checkpoint did **not** complete: workers
did not reach a checkpoint-safe lease before the bounded verification timeout.
This is a release-gate failure, not a passing HA claim.

The raw sanitized result is in `results.json`; it records the failure reason and
the source/test configuration is the checked-in verifier. No production services,
volumes, credentials, or cloud resources were used.

## Reproduce

```powershell
uv run python scripts/verify_postgres_training_failover.py `
  --output artifacts/postgres-training-failover-20261108/results.json
```

The verifier removes its temporary Docker network, containers, and volumes in a
`finally` block. The current limitation is that active worker session recovery
must be made checkpoint-safe before this gate can close.
