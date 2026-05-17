"""Module entry point for ``python -m ha_mqtt_agent``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
