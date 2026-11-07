# Python package publication

ParamMesh keeps package publication separate from normal CI. The manual
[`Publish Python package`](../.github/workflows/publish-python.yml) workflow
checks out the selected Git ref, builds from the locked source, and publishes
through PyPI Trusted Publishing using GitHub's short-lived OIDC identity. No
long-lived PyPI token belongs in GitHub Actions or this repository.

The repository owner has configured a pending publisher for the first release
with:

- owner: `fetachino`
- repository: `paramesh`
- workflow: `publish-python.yml`
- environment: empty (`Any` in PyPI's display)

This pending publisher creates the `paramesh` project on its first successful
upload and then becomes the project's normal trusted publisher. The next
publication must use the immutable `v1.1.0` tag; the existing `v1.0.0` tag is
unchanged.

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
independent clean-environment install are recorded.
