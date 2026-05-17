# Developer Notes

This scaffold is intentionally opinionated.

## User Guides

- [Home Assistant Setup](home-assistant-setup.md): configure MQTT discovery,
  confirm the host device, and add its energy sensor to the Energy dashboard.

## Included Defaults

- `uv` for environment and package management
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
4. Preserve `make install` as the durable user-facing installation path unless
   you have a reason to redesign distribution.
