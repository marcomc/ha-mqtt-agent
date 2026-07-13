#!/usr/bin/env sh
set -eu

SERVICE_NAME="ha-mqtt-agent"
SERVICE_USER="ha-mqtt-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_DIR="/etc/ha-mqtt-agent"
CONFIG_PATH="${CONFIG_DIR}/config.toml"
STATE_DIR="/var/lib/ha-mqtt-agent"
STATE_PATH="${STATE_DIR}/state.json"
APP_HOME="/opt/ha-mqtt-agent"
APP_VENV="${APP_HOME}/venv"
APP_PYTHON="${APP_VENV}/bin/python"
BINARY_PATH="/usr/local/bin/ha-mqtt-agent"
KNOWN_OPTIONAL_PACKAGES=" iw lm-sensors upower "
RECOMMENDED_OPTIONAL_PACKAGES="iw lm-sensors upower"
NOLOGIN_PATH="/usr/sbin/nologin"

PROJECT_ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
NON_INTERACTIVE=0
ENABLE_OPTIONAL_SENSORS=0
OPTIONAL_PACKAGES=""

usage() {
  cat <<EOF
usage: install-systemd-service.sh [--non-interactive] [--enable-optional-sensors] [--optional-packages LIST]
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --non-interactive)
      NON_INTERACTIVE=1
      ;;
    --enable-optional-sensors)
      ENABLE_OPTIONAL_SENSORS=1
      ;;
    --optional-packages)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--optional-packages requires a comma-separated list" >&2
        exit 2
      fi
      OPTIONAL_PACKAGES=$1
      ;;
    --optional-packages=*)
      OPTIONAL_PACKAGES=${1#*=}
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

OS_NAME=$(uname -s)
CURRENT_UID=$(id -u)

if [ "${OS_NAME}" != "Linux" ]; then
  echo "systemd install is supported on Linux only." >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; this install path requires systemd." >&2
  exit 1
fi

if [ "${CURRENT_UID}" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
  echo "sudo not found; run as root or install sudo for setup." >&2
  exit 1
fi

if [ ! -x "${NOLOGIN_PATH}" ]; then
  if [ -x /sbin/nologin ]; then
    NOLOGIN_PATH="/sbin/nologin"
  else
    NOLOGIN_PATH="/bin/false"
  fi
fi

run_root() {
  if [ "${CURRENT_UID}" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' apt
  elif command -v dnf >/dev/null 2>&1; then
    printf '%s\n' dnf
  elif command -v pacman >/dev/null 2>&1; then
    printf '%s\n' pacman
  else
    printf '%s\n' none
  fi
}

validate_optional_package() {
  case "${KNOWN_OPTIONAL_PACKAGES}" in
    *" $1 "*)
      ;;
    *)
      echo "Unknown optional package: $1" >&2
      echo "Known optional packages:${KNOWN_OPTIONAL_PACKAGES}" >&2
      exit 2
      ;;
  esac
}

space_list_from_csv() {
  printf '%s\n' "$1" | tr ',' ' '
}

optional_packages_to_install() {
  if [ -n "${OPTIONAL_PACKAGES}" ]; then
    space_list_from_csv "${OPTIONAL_PACKAGES}"
    return 0
  fi
  if [ "${ENABLE_OPTIONAL_SENSORS}" -eq 1 ]; then
    printf '%s\n' "${RECOMMENDED_OPTIONAL_PACKAGES}"
    return 0
  fi
  if [ "${NON_INTERACTIVE}" -eq 1 ]; then
    printf '\n'
    return 0
  fi

  printf 'Install optional sensor packages (%s)? [y/N] ' "${RECOMMENDED_OPTIONAL_PACKAGES}" >&2
  read -r answer
  case "${answer}" in
    y|Y|yes|YES)
      printf '%s\n' "${RECOMMENDED_OPTIONAL_PACKAGES}"
      ;;
    *)
      printf '\n'
      ;;
  esac
}

install_optional_packages() {
  packages=$1
  if [ -z "${packages}" ]; then
    return 0
  fi

  for package in ${packages}; do
    validate_optional_package "${package}"
    package_manager=$(detect_package_manager)
    case "${package_manager}" in
      apt)
        run_root apt-get install -y "${package}"
        ;;
      dnf)
        run_root dnf install -y "${package}"
        ;;
      pacman)
        run_root pacman -S --needed --noconfirm "${package}"
        ;;
      *)
        echo "No supported package manager found. Install optional package manually: ${package}" >&2
        ;;
    esac
  done
}

STANDALONE_PYTHON=${STANDALONE_PYTHON:-$(./scripts/find-standalone-python.sh)}
if ! command -v "${STANDALONE_PYTHON}" >/dev/null 2>&1; then
  echo "${STANDALONE_PYTHON} not found." >&2
  exit 1
fi

cd "${PROJECT_ROOT}"

OPTIONAL_TO_INSTALL=$(optional_packages_to_install)
install_optional_packages "${OPTIONAL_TO_INSTALL}"

if ! getent group "${SERVICE_USER}" >/dev/null 2>&1; then
  run_root groupadd --system "${SERVICE_USER}"
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  run_root useradd \
    --system \
    --gid "${SERVICE_USER}" \
    --home-dir "${STATE_DIR}" \
    --shell "${NOLOGIN_PATH}" \
    "${SERVICE_USER}"
fi

SUPPLEMENTARY_GROUPS_DIRECTIVE=""
if command -v vcgencmd >/dev/null 2>&1 && getent group video >/dev/null 2>&1; then
  SUPPLEMENTARY_GROUPS_DIRECTIVE="SupplementaryGroups=video"
fi

run_root install -d -m 0755 "${APP_HOME}" "$(dirname -- "${BINARY_PATH}")" "${CONFIG_DIR}"
run_root install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_DIR}"
run_root rm -rf "${APP_VENV}"
run_root "${STANDALONE_PYTHON}" -m venv "${APP_VENV}"
run_root "${APP_PYTHON}" -m pip install --upgrade pip
run_root "${APP_PYTHON}" -m pip install "${PROJECT_ROOT}"
run_root ln -sf "${APP_VENV}/bin/ha-mqtt-agent" "${BINARY_PATH}"

if [ ! -f "${CONFIG_PATH}" ]; then
  tmp_config=$(mktemp)
  "${APP_PYTHON}" -m ha_mqtt_agent.installer render-config \
    --template "${PROJECT_ROOT}/config.toml.example" \
    --output "${tmp_config}" \
    --state-path "${STATE_PATH}"
  run_root install -m 0640 -o root -g "${SERVICE_USER}" "${tmp_config}" "${CONFIG_PATH}"
  rm -f "${tmp_config}"
  echo "Installed config template to ${CONFIG_PATH}"
else
  echo "Config already exists at ${CONFIG_PATH}"
fi

tmp_service=$(mktemp)
cat >"${tmp_service}" <<EOF
[Unit]
Description=Home Assistant MQTT Agent
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
${SUPPLEMENTARY_GROUPS_DIRECTIVE}
ExecStart=${BINARY_PATH} --config ${CONFIG_PATH} run
Restart=always
RestartSec=5
StateDirectory=ha-mqtt-agent

[Install]
WantedBy=multi-user.target
EOF

run_root install -m 0644 -o root -g root "${tmp_service}" "${SERVICE_FILE}"
rm -f "${tmp_service}"
run_root systemctl daemon-reload
run_root systemctl enable "${SERVICE_NAME}"
run_root systemctl restart "${SERVICE_NAME}"

echo "Installed and started ${SERVICE_NAME}"
echo "Config: ${CONFIG_PATH}"
echo "State: ${STATE_PATH}"
echo "Logs: journalctl -u ${SERVICE_NAME}"
