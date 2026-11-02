# Reproducible Python dependencies

`pyproject.toml` declares direct requirements. `uv.lock` fixes transitive versions,
package sources and artifact hashes for Python 3.12 on Windows AMD64 and Linux
x86-64/ARM64. Linux ARM64 was built and exercised under local emulation; native
ARM64 hardware remains to be checked. Other Python versions, operating systems
and architectures are not validated targets.
PyTorch uses an explicit official CPU index; other packages resolve from PyPI.
The build backend is separately pinned in `build-system.requires`.

```powershell
python -m pip install uv==0.13.6
uv sync --locked --all-extras --python 3.12
uv lock --check
```

Activate `.venv` before running the existing test/operator commands. Sync is exact:
it removes undeclared packages from the selected environment. To preserve an existing
environment while validating, set `UV_PROJECT_ENVIRONMENT` to a separate local path.
Do not use an existing environment as the source of dependency truth.

CI uses the pinned uv release, rejects stale locks, installs all test extras and
audits that installed dependency graph. Docker uses a digest-pinned uv binary and
installs only train/storage/operations extras from the same lock. Source changes
reuse the cached dependency layer. No wheel mirror or cloud credentials are needed.
The optional `benchmark` extra supplies Matplotlib and bounded RPC capture dependencies;
it is included by `--all-extras` and excluded from the training image.
CI also installs only train/benchmark extras into a separate environment and runs
a tiny CLI contract check, so hidden dependencies on operations extras are caught.
The Python base image remains the existing `python:3.12-slim`; this locks Python
packages, not the underlying OS packages or bit-for-bit image output.

For an intentional dependency update, change its direct requirement if necessary,
then run `uv lock --upgrade-package <package>`. Review the lock diff, run static
checks/tests/audit and both Compose verifiers, and commit metadata and lock together.
Use the same branch/PR checks as application changes. Do not use `--frozen` to conceal
a stale lock or regenerate all dependencies during normal startup.

See [uv locking semantics](https://docs.astral.sh/uv/concepts/projects/sync/) and
[official CPU-index configuration](https://docs.astral.sh/uv/guides/integration/pytorch/).
The lockfile contains public registry URLs and hashes, never credentials or local notes.
