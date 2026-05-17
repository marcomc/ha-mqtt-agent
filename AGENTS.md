# Project Agent Notes

## Project Identity

- Project name: `Home Assistant MQTT Agent`
- Python package: `ha_mqtt_agent`
- Installed CLI: `ha-mqtt-agent`
- Module entry point: `python -m ha_mqtt_agent`
- Default user config path: `~/.config/ha-mqtt-agent/config.toml`
- Default standalone runtime path: `~/.local/share/ha-mqtt-agent/venv`
- Default user-facing binary path: `~/.local/bin/ha-mqtt-agent`
- Default macOS service: user LaunchAgent
  `com.marcomc.ha-mqtt-agent`

## New Chat Bootstrap

At the start of every new AI agent chat for this repository, read:

1. `README.md`
2. `Makefile`
3. `pyproject.toml`
4. `CHANGELOG.md`
5. `TODO.md`

## Development Rules

- Keep the project installable as a packaged Python CLI.
- Keep importable application code under `src/ha_mqtt_agent/`.
- Keep tests under `tests/`.
- Prefer focused modules instead of one large `cli.py`.
- Keep `python -m ha_mqtt_agent` working.
- Preserve the standalone install behavior of `make install`.
- Preserve the user LaunchAgent behavior of `make install-agent`.

## Quality Gates

Use `make check` as the default maintainer validation command.

Expected checks:

- `uv run pytest -q`
- `uv run ruff check src tests`
- `uv run ruff format --check src tests`
- `uv run mypy src tests`
- `markdownlint --config .markdownlint.json README.md CHANGELOG.md TODO.md AGENTS.md docs/*.md`
- `shellcheck --enable=all scripts/*.sh`

## Documentation Rules

- Keep `README.md` accurate for end users.
- Keep `CHANGELOG.md` updated in `Unreleased` for user-visible changes.
- Remove completed items from `TODO.md` when they ship.
- Update config documentation when adding or changing config keys.
- Keep read-only CLI commands such as `info` and `sample` free of persistent
  writes, network publishes, and service changes.
- When adding or changing config keys, keep loader validation, schema bounds,
  examples, docs, and tests synchronized.

## Release Hygiene

When cutting a release, update the version consistently in:

- `pyproject.toml`
- `src/ha_mqtt_agent/__init__.py`
- `CHANGELOG.md`
- tests that assert the version string
