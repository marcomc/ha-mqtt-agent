# Developer Notes

This scaffold is intentionally opinionated.

## User Guides

- [Home Assistant Setup](home-assistant-setup.md): configure MQTT discovery,
  confirm the host device, and add its energy sensor to the Energy dashboard.

## Installer Shape

`scripts/install.sh` is the user-facing entrypoint for a new Mac. It validates
basic prerequisites and delegates to `make install-agent`.

The `Makefile` remains the durable automation API for install, restart, status,
uninstall, development checks, and tests. Keep installer shell code thin so the
operational behavior is defined in one place.

## Included Defaults

- `uv` for development environment and package management
- local `python3` plus `pip` for the installed standalone runtime
- `src/` package layout
- `argparse` for a small CLI surface
- TOML config loading via `tomllib`
- strict-enough static checks for early signal without heavy ceremony

## Intended Workflow

1. Generate a new project from the template.
2. Keep sensor collection, energy accumulation, and MQTT publishing in separate
   modules.
3. Keep `README.md`, `CHANGELOG.md`, and `TODO.md` current as the project
   evolves.
4. Preserve `make install-agent` as the durable service installation path unless
   you have a reason to redesign distribution.
