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

The `1.1.0` package was published through the trusted workflow from tag
`v1.1.0` in run `42406474933`. An isolated public-wheel smoke test confirmed:

```text
uvx --from "paramesh[train]==1.1.0" paramesh-local --help
```

The command installed the published package and train extra, then returned the
launcher help without using repository files or credentials.
