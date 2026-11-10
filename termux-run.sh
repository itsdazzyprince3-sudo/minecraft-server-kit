#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ -z "${TERMUX_VERSION:-}" && "${PREFIX:-}" != *"/com.termux/files/usr" ]]; then
  echo "This launcher is Termux-only. On desktop Linux, keep using ./run.sh with Docker Engine and Compose v2." >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python is missing. Run: bash install-termux.sh" >&2
  exit 1
fi
if ! command -v java >/dev/null 2>&1; then
  echo "Java is missing. Run: bash install-termux.sh" >&2
  exit 1
fi
exec python3 native/manager.py "$@"
