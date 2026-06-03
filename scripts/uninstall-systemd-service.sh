#!/usr/bin/env sh
set -eu

SERVICE_NAME="ha-mqtt-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
APP_HOME="/opt/ha-mqtt-agent"
BINARY_PATH="/usr/local/bin/ha-mqtt-agent"

OS_NAME=$(uname -s)
CURRENT_UID=$(id -u)

if [ "${OS_NAME}" != "Linux" ]; then
  echo "systemd uninstall is supported on Linux only." >&2
  exit 1
fi

if [ "${CURRENT_UID}" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
  echo "sudo not found; run as root or install sudo for setup." >&2
  exit 1
fi

run_root() {
  if [ "${CURRENT_UID}" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

if command -v systemctl >/dev/null 2>&1; then
  set +e
  run_root systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1
  DISABLE_STATUS=$?
  set -e
  if [ "${DISABLE_STATUS}" -ne 0 ]; then
    :
  fi
fi

run_root rm -f "${SERVICE_FILE}"
run_root rm -f "${BINARY_PATH}"
run_root rm -rf "${APP_HOME}"

if command -v systemctl >/dev/null 2>&1; then
  run_root systemctl daemon-reload
fi

echo "Stopped and removed ${SERVICE_NAME}"
echo "Removed runtime: ${APP_HOME}"
echo "Removed binary: ${BINARY_PATH}"
echo "Preserved config/state under /etc/ha-mqtt-agent and /var/lib/ha-mqtt-agent"
