#!/usr/bin/env sh
set -eu

print_if_supported() {
  candidate=$1
  if [ -z "${candidate}" ]; then
    return 0
  fi
  if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    printf '%s\n' "${candidate}"
    exit 0
  fi
}

if [ -n "${STANDALONE_PYTHON:-}" ]; then
  print_if_supported "${STANDALONE_PYTHON}"
  echo "${STANDALONE_PYTHON} must be Python 3.11 or newer." >&2
  exit 1
fi

for name in python3.14 python3.13 python3.12 python3.11 python3; do
  if candidate=$(command -v "${name}" 2>/dev/null); then
    print_if_supported "${candidate}"
  fi
done

if command -v uv >/dev/null 2>&1; then
  for version in 3.14 3.13 3.12 3.11; do
    if candidate=$(uv python find "${version}" 2>/dev/null); then
      print_if_supported "${candidate}"
    fi
  done
fi

echo "Python 3.11 or newer not found." >&2
echo "Install Python 3.11+ or uv-managed Python, then rerun this command." >&2
exit 1
