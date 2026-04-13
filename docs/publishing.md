# Publishing

`pytest-warmup` is configured for GitHub Actions based publishing through PyPI Trusted Publishing.

The repository-side workflow lives at:

- [`.github/workflows/publish.yml`](../.github/workflows/publish.yml)

## Recommended Setup

Use PyPI Trusted Publishing instead of storing API tokens in GitHub secrets.

For a new project on PyPI, create a pending publisher. For an existing project, add a trusted publisher entry.

Repository settings to use:

- owner: `kaor4bp`
- repository: `pytest-warmup`
- workflow file: `.github/workflows/publish.yml`
- environment: `pypi`

## GitHub Setup

Create a GitHub environment named `pypi`.

Recommended:

- require manual approval for the `pypi` environment if you want an explicit human gate before publishing;
- keep publishing on release publication and optional manual dispatch;
- do not store long-lived PyPI tokens in repository secrets if Trusted Publishing is enabled.

## Release Flow

1. Update [`CHANGELOG.md`](../CHANGELOG.md).
2. Pick the next release tag, for example `0.1.6`.
3. Run the local verification steps:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m build
./.venv/bin/python -m twine check dist/*
```

4. Commit and push the release changes.
5. Create a Git tag and GitHub release for that version, or run the publish workflow manually.
6. Approve the `pypi` environment if required.

`pytest-warmup` uses VCS-driven package versions through Git tags. The version is no longer hard-coded in [`pyproject.toml`](../pyproject.toml); the build backend derives it from the checked-out tag. For release builds, make sure the workflow has access to tags.

## What the Workflow Does

The publish workflow:

- checks out the repository;
- builds `sdist` and `wheel`;
- runs `twine check dist/*`;
- uploads the built distributions as an artifact;
- publishes the distributions to PyPI through `pypa/gh-action-pypi-publish`.

## Notes

- The workflow is intentionally separate from CI so routine pull requests do not attempt publication.
- Trusted Publishing is the preferred path for public PyPI releases because it avoids token handling in CI.
