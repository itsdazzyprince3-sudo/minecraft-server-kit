#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[[ -n "${TERMUX_VERSION:-}" || "${PREFIX:-}" == *"/com.termux/files/usr" ]] || fail "Run this inside the official Termux app, not desktop Linux or an Android shell without Termux."
arch="$(uname -m)"
[[ "$arch" == "aarch64" || "$arch" == "arm64" ]] || fail "This native installer supports Android ARM64 only; detected $arch. Use Docker mode on a Linux computer instead."
[[ -n "${PREFIX:-}" && -d "$PREFIX" ]] || fail "Termux PREFIX is not set. Open the Termux app and retry."

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
case "$repo_dir" in
  /storage/emulated/*|/sdcard/*) fail "Keep the repository in Termux's private home directory (for example ~/minecraft-server-kit), not shared Android storage; shared storage does not support the required file permissions." ;;
esac

missing=()
command -v python3 >/dev/null 2>&1 || missing+=(python)
if ! dpkg-query -W -f='${Status}' openjdk-25 2>/dev/null | grep -q 'install ok installed'; then
  missing+=(openjdk-25)
fi
if ((${#missing[@]})); then
  echo "Installing missing Termux packages: ${missing[*]} (Python runs the local panel; OpenJDK 25 runs Paper 26.1+)."
  pkg update -y
  pkg install -y "${missing[@]}"
else
  echo "Python and OpenJDK 25 packages are already installed."
fi

command -v python3 >/dev/null 2>&1 || fail "Python installation did not provide python3. Check the Termux package mirror and retry."
command -v java >/dev/null 2>&1 || fail "Java is not on PATH after OpenJDK 25 installation. Reopen Termux and retry."
java_out="$(java -version 2>&1 || true)"
java_major="$(JAVA_VERSION_OUTPUT="$java_out" python3 - <<'PY'
import os, re
text = os.environ.get("JAVA_VERSION_OUTPUT", "")
match = re.search(r'version\s+"?([0-9]+)(?:\.([0-9]+))?', text, re.I)
if not match:
    match = re.search(r'(?m)^\s*(?:openjdk|java)\s+([0-9]+)(?:\.([0-9]+))?', text, re.I)
print((int(match.group(2)) if match and match.group(1) == "1" else int(match.group(1))) if match else 0)
PY
)"
((java_major >= 25)) || fail "Paper 26.1+ requires Java 25. Detected Java ${java_major:-unknown}; ensure openjdk-25 is installed and selected."

available_kb="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
[[ "$available_kb" =~ ^[0-9]+$ ]] || fail "Could not determine free storage in $HOME."
available_gb=$((available_kb / 1024 / 1024))
((available_kb >= 1572864)) || fail "Only ${available_gb} GB is free. Free at least 1.5 GB for the server JAR and initial files; a world needs additional storage."
((available_kb >= 5242880)) || echo "Warning: less than 5 GB is free. A growing Minecraft world may fill storage; keep backups."

mkdir -p "$repo_dir/data/plugins" "$repo_dir/config" "$repo_dir/native"
if [[ ! -f "$repo_dir/.env" ]]; then
  cp "$repo_dir/.env.example" "$repo_dir/.env"
  chmod 600 "$repo_dir/.env"
  echo "Created .env from .env.example; existing worlds/config were not touched."
else
  echo "Keeping existing .env unchanged."
fi
if [[ ! -f "$repo_dir/native/config.json" ]]; then
  printf '{\n  "memory": "1G",\n  "paper_channel": "STABLE",\n  "panel_port": 8080\n}\n' > "$repo_dir/native/config.json"
  echo "Created native/config.json with a conservative 1G RAM default."
else
  echo "Keeping existing native/config.json unchanged."
fi

printf '\nTermux prerequisites are ready. No worlds or existing configuration were overwritten.\nNext: bash termux-run.sh\n'
