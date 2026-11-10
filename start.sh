#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

native_only=false
if [[ "${1:-}" == "--native" ]]; then
  native_only=true
  shift
fi

is_termux=false
if [[ -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == *"/com.termux/files/usr" ]]; then
  is_termux=true
fi

if [[ "$is_termux" == true ]]; then
  if ! command -v python3 >/dev/null 2>&1 || ! command -v java >/dev/null 2>&1 \
      || ! dpkg-query -W -f='${Status}' openjdk-25 2>/dev/null | grep -q 'install ok installed'; then
    bash ./install-termux.sh
  fi
  exec python3 native/manager.py "$@"
fi

case "$(uname -s 2>/dev/null || true)" in
  MINGW*|MSYS*|CYGWIN*)
    echo "Use .\\start.ps1 from Windows PowerShell for Docker Desktop." >&2
    exit 2
    ;;
esac

if [[ "$native_only" == false ]] && command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    if ! docker compose version >/dev/null 2>&1; then
      echo "Docker Compose is required when using Docker. Install Compose v2 and retry." >&2
      exit 1
    fi
    exec bash ./run.sh "$@"
  fi
  echo "Docker is installed but its engine is unavailable; trying native Paper mode."
fi

if [[ "$(uname -s 2>/dev/null || true)" != "Linux" && "$(uname -s 2>/dev/null || true)" != "Darwin" ]]; then
  echo "Native Paper mode needs Linux/macOS, Python 3, and a compatible Java runtime. Windows PowerShell users can run .\\start.ps1 with Docker Desktop." >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required for native Paper mode. Install Python 3 and retry; Termux installs it automatically." >&2
  exit 1
fi
if ! command -v java >/dev/null 2>&1; then
  echo "A Java runtime compatible with the selected Minecraft version is required for native Paper mode. Install Java 25 for current Paper, then retry." >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 \
    && docker ps --filter name=mc-server --format '{{.Names}}' | grep -qx 'mc-server'; then
  echo "The Docker server container is already running. Stop it before using native mode against the same data/ directory." >&2
  exit 1
fi

echo "Starting native Paper mode. This mode supports Paper; use Docker for Vanilla/Fabric/Forge/NeoForge."
exec python3 native/manager.py "$@"
