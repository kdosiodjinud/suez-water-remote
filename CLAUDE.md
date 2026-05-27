# CLAUDE.md

Project guidance for Claude Code when working in this repository.

## Language

All repository artifacts are written in **English**:

- Source code, identifiers, and comments
- Docstrings and documentation (README, etc.)
- Git branch names and commit messages
- GitHub release titles and notes
- Pull request titles and descriptions

Conversation with the maintainer may be in Czech, but anything committed to the
repository or published (commits, branches, releases, PRs) must be in English.

## Development

- This is a Home Assistant custom integration; the `homeassistant` package is
  **not** installed in the dev/CI environment. Unit tests run against minimal
  HA stubs in `tests/conftest.py`, and mypy ignores `homeassistant.*`
  (`[[tool.mypy.overrides]]` in `pyproject.toml`).
- **Stub names must match the real HA API exactly.** A stub with a wrong name
  silently masks a bad import and lets tests pass while the integration fails to
  load in Home Assistant (e.g. the recorder model is `StatisticMetaData`, not
  `StatisticMetadata`). When adding a new HA import, double-check the symbol
  name against Home Assistant source before stubbing it.
- Before committing, run all gates:
  - `.venv/bin/ruff check .`
  - `.venv/bin/mypy custom_components/suez_water_remote` and `.venv/bin/mypy tests`
    (run separately — a combined invocation reports "source file found twice"
    because `custom_components/` has no `__init__.py`)
  - `.venv/bin/pytest -q`

## Releases

HACS pulls versions from GitHub releases. To cut a release: bump `version` in
both `custom_components/suez_water_remote/manifest.json` and `pyproject.toml`,
commit, push to `main`, then `gh release create vX.Y.Z --latest`.
