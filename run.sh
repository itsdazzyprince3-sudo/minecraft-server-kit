#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 (Linux), then rerun ./run.sh." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required (docker compose). Install/update Docker Desktop or the Docker Compose plugin." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running or your user cannot access it. Start Docker and rerun." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  secret="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  sed -i.bak "s/^RCON_PASSWORD=.*/RCON_PASSWORD=${secret}/" .env && rm -f .env.bak
  echo "Created .env with a random private RCON password. Keep .env private; it is git-ignored."
fi
env_value() { sed -n "s/^$1=//p" .env | head -n 1; }

if [[ "$(env_value EULA)" != "TRUE" ]]; then
  echo "Please read the Minecraft EULA: https://aka.ms/MinecraftEULA"
  read -r -p "Do you accept the Minecraft EULA? Type yes to continue: " answer
  if [[ "${answer,,}" != "yes" ]]; then
    echo "Not starting. To launch later, rerun ./run.sh and accept the EULA."
    exit 1
  fi
  sed -i.bak 's/^EULA=.*/EULA=TRUE/' .env && rm -f .env.bak
fi

if grep -q '^RCON_PASSWORD=change-me$' .env; then
  secret="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  sed -i.bak "s/^RCON_PASSWORD=.*/RCON_PASSWORD=${secret}/" .env && rm -f .env.bak
fi

mkdir -p data
export PROJECT_DIR="$(pwd -P)"
printf 'Building/starting Minecraft server and local control panel.\n\nPanel: http://localhost:%s\nJava: localhost:%s (TCP)\nBedrock: localhost:%s (UDP)\n\nPress Ctrl+C in this terminal to stop both containers.\n\n' \
  "$(env_value PANEL_PORT)" "$(env_value JAVA_PORT)" "$(env_value BEDROCK_PORT)"
exec docker compose --project-name mcstack up --build
