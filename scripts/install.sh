#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
CONFIG_PATH="${HOME}/.config/ha-mqtt-agent/config.toml"

cd "${PROJECT_ROOT}"

OS_NAME=$(uname -s)
if [ "${OS_NAME}" != "Darwin" ]; then
  echo "Home Assistant MQTT Agent currently supports macOS only." >&2
  exit 1
fi

if ! command -v make >/dev/null 2>&1; then
  echo "make not found. Install Xcode Command Line Tools, then rerun this script." >&2
  echo "Try: xcode-select --install" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.11 or newer, then rerun this script." >&2
  exit 1
fi

if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc not found. Install Xcode Command Line Tools, then rerun this script." >&2
  echo "Try: xcode-select --install" >&2
  exit 1
fi

if ! command -v codesign >/dev/null 2>&1; then
  echo "codesign not found. Install Xcode Command Line Tools, then rerun this script." >&2
  echo "Try: xcode-select --install" >&2
  exit 1
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "python3 must be version 3.11 or newer." >&2
  exit 1
}

make install-agent

echo
echo "Installed Home Assistant MQTT Agent."
echo "Edit the MQTT settings in ${CONFIG_PATH}, then run:"
echo "  make restart-agent"
