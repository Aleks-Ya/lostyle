# Developer Guide

## Set up a Python virtual environment
The project is managed by [uv](https://docs.astral.sh/uv/): `uv sync` creates `.venv/` with the
`dev` dependency group, resolved from the committed `uv.lock`. Prefix commands with `uv run`.

## Checks
```bash
uv run pytest                                  # tests (LibreOffice round-trips skip without soffice)
uv run ruff check . && uv run ruff format .    # lint and format
uv run mypy                                    # strict type check of src/
```
The same checks run in GitHub Actions on every push and pull request
(`.github/workflows/unit-tests.yml`): https://github.com/Aleks-Ya/lostyle/actions

## Release a new version
1. Checkout branch `main`, run the checks, `git push`, and wait for GitHub Actions to pass.
2. Increment version (the single source is `__version__` in `src/lostyle/__init__.py`):
    1. Show the next versions: `uv run bump-my-version show-bump`
    2. Switch a dev version to RELEASE (`0.1.1.dev0` -> `0.1.1`): `uv run bump-my-version bump release --tag`
    3. Switch the RELEASE version to the next dev (`0.1.1` -> `0.2.0.dev0`): `uv run bump-my-version bump minor`
3. Create a GitHub release:
    1. Push branch and tags: `git push origin HEAD --tags`
    2. Create a release from the tag: `gh release create v0.1.1 --generate-notes`
       (or https://github.com/Aleks-Ya/lostyle/releases)
    3. Wait for GitHub Actions to finish publishing to PyPI: https://github.com/Aleks-Ya/lostyle/actions
    4. Verify the version: `uvx --refresh lostyle --version`

## Publish to PyPI
PyPI package: https://pypi.org/project/lostyle

Publishing is automated: creating a GitHub release runs `.github/workflows/publish.yml`
(PyPI Trusted Publishing, no API tokens).

One-time setup on [pypi.org](https://pypi.org/manage/account/publishing/): add a Trusted Publisher for
this project pointing at repo `Aleks-Ya/lostyle`, workflow `publish.yml`, environment `pypi`
(add it as a "pending publisher" before the first release).

Manual build/publish (fallback):
```bash
uv build                   # creates dist/*.whl and dist/*.tar.gz
uv publish                 # requires a PyPI API token (UV_PUBLISH_TOKEN)
```
Note: builds from a `.dev0` checkout produce a development version; only released (non-`.dev`) tags
yield a clean PyPI version.
