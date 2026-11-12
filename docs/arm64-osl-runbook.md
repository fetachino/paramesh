# Persistent ARM64 validation runbook

This runbook applies only if the OSU Open Source Lab (OSL) approves the
ParamMesh AArch64 hosting request. It is a disposable validation procedure,
not a production deployment plan.

## Before access is granted

- Keep the request limited to synthetic data and disposable credentials.
- Submit only the public half of the SSH key pair. Keep the private key outside
  the repository and never paste it into an issue or log.
- Record the OSL ticket number and the exact ParamMesh source SHA to validate.
- Do not connect the ARM hosts to the existing Google Cloud or Coolify network.

OSL's AArch64 OpenStack service is intended for functional development and CI;
it is not a substitute for a dedicated performance benchmark environment.

## Initial access

After OSL provides the VM addresses and login instructions, verify each host
before installing anything:

```bash
ssh -i ~/.ssh/paramesh-osl-arm ubuntu@<arm-host>
uname -m
docker version
df -h /
free -h
```

`uname -m` must report `aarch64`. Stop if either host is not ARM64 or the
provided account cannot use Docker without weakening host security.

## Isolated deployment

Use a separate Compose project name and disposable environment file. Do not
reuse production volumes, credentials, networks, checkpoints, or DNS routes.

```bash
git clone https://github.com/fetachino/paramesh.git
cd paramesh
git checkout <validated-sha>
docker compose -p paramesh-arm64 --profile operations --profile storage \
  -f compose.yaml -f compose.arm64-validation.yaml up -d --no-build
```

Record the source SHA, image digests, Compose configuration hash, host
architecture, and container platform before training.

## Validation sequence

1. Confirm coordinator, both shards, workers, dashboard authentication, and
   internal telemetry are healthy.
2. Run the deterministic CPU reference workload and save sanitized JSON,
   checkpoint manifests, shard versions, and SHA-256 checksums.
3. Abort one checkpoint, verify the abort is visible on every shard, then run a
   second checkpoint and verify equal shard versions.
4. Reboot one host only after all workers are stopped and durable state is
   exported. Restore the isolated project and verify the same manifest and
   parameter hashes.
5. Exercise worker interruption and recovery without using production state.

Keep raw evidence outside Git when it contains addresses, credentials, or
private logs. Commit only sanitized summaries and checksums.

## Cleanup

Stop and remove the isolated Compose project, disposable volumes, temporary
firewall rules, DNS records, and any attached storage after evidence capture.
Confirm the OSL hosts no longer contain ParamMesh credentials or checkpoints.

The result can establish native ARM64 functional validation and persistence
behavior. It cannot, by itself, establish production ARM hosting, HA, GPU
support, or broad performance scaling.
