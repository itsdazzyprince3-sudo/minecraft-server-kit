#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ -z "${TERMUX_VERSION:-}" && "${PREFIX:-}" != *"/com.termux/files/usr" ]]; then
  echo "This launcher is Termux-only. On desktop Linux, keep using ./run.sh with Docker Engine and Compose v2." >&2
  exit 2
fi
needs_install=false
command -v python3 >/dev/null 2>&1 || needs_install=true
command -v java >/dev/null 2>&1 || needs_install=true
if ! dpkg-query -W -f='${Status}' openjdk-25 2>/dev/null | grep -q 'install ok installed'; then
  needs_install=true
fi
if [[ "$needs_install" == true ]]; then
  bash ./install-termux.sh
fi
exec python3 native/manager.py "$@"
