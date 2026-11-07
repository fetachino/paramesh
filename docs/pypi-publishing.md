# Python package publication

ParamMesh keeps package publication separate from normal CI. The manual
[`Publish Python package`](../.github/workflows/publish-python.yml) workflow
checks out the selected Git ref, builds from the locked source, and publishes
through PyPI Trusted Publishing using GitHub's short-lived OIDC identity. No
long-lived PyPI token belongs in GitHub Actions or this repository.

Before the first publication, the repository owner must create the `paramesh`
project on PyPI (or configure its pending publisher) for:

- owner: `fetachino`
- repository: `paramesh`
- workflow: `publish-python.yml`
- environment: empty unless a PyPI environment is deliberately configured

The workflow is intentionally manual. Select the exact release tag or commit
for the package version being published; never rebuild from an unreviewed branch
or republish an existing version. After PyPI confirms the release, verify it
from a clean environment with:

```powershell
python -m pipx install "paramesh[train]"
paramesh-local --help
```

The current repository contains the packaged `paramesh-local` entry point, but
publication is not claimed until a successful trusted workflow run and an
independent clean-environment install are recorded. The stable `v1.0.0` tag is
immutable; post-release usability additions should use the next release version.
