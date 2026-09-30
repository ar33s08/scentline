# Release checklist (Scentline → PyPI)

The `publish.yml` workflow is wired but **dormant**: it needs two one-time
steps, both owned by you, before `v0.2.1` (or later) can ship to PyPI.

1. **PyPI** → your account → *Add a new API token → Trusted publisher →
   GitHub Actions* and bind it to:
   - repository: `ar33s08/scentline`
   - workflow name: `publish.yml` (exact)
   - environment name: `pypi` (create the GitHub repo Settings →
     Environments → `pypi` entry first and point it at the PyPI OIDC
     provider so the `environment: pypi` gate passes)
2. **Cut a release**: bump `version` in `pyproject.toml` +
   `scentline/__init__.py`, tag it, and publish the GitHub Release —
   `git tag -a v0.2.1 -m "..." && git push origin v0.2.1`, then draft a
   release from the tag in the web UI.

CI then: runs the full suite + zero-dep gate → builds wheel + sdist →
`pypa/gh-action-pypi-publish` with OIDC (long-lived tokens stay unused).

Quick local alternative if you don't want to wire CI yet:
`pipx install twine && python -m build && twine upload dist/*`
(choose "API token" when prompted; scope the PyPI token to the project).
