#!/usr/bin/env python3
"""Native Paper server and localhost control page for Android Termux (no Docker)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from runtime import (
    build_java_args,
    is_termux,
    java_major_from_version,
    normalize_arch,
    parse_env_file,
    parse_memory_mb,
    required_java_for_paper,
    stop_process,
    update_env_file,
    validate_port,
    validate_server_settings,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NATIVE = ROOT / "native"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "native-server.log"
STATE_FILE = NATIVE / "server-version.json"
NATIVE_CONFIG = NATIVE / "config.json"
PAPER_API = "https://fill.papermc.io/v3"
USER_AGENT = "MinecraftServerKit/0.2.0 (https://github.com/itsdazzyprince3-sudo/minecraft-server-kit)"


def request_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def download_file(url: str, destination: Path, expected_sha256: str | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".download")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=90) as response, temp.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected_sha256 and actual.lower() != expected_sha256.lower():
            raise RuntimeError("Downloaded server JAR failed SHA-256 verification; the existing JAR was left untouched.")
        temp.replace(destination)
        return actual
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def resolve_paper_version(requested: str) -> str:
    if requested.upper() != "LATEST":
        return requested
    listing = request_json(f"{PAPER_API}/projects/paper")
    groups = listing.get("versions", {})
    for versions in groups.values():
        if versions:
            return versions[0]
    raise RuntimeError("PaperMC returned no available Paper versions.")


def get_paper_build(version: str, channel: str) -> dict[str, Any]:
    channel = channel.upper()
    if channel not in {"STABLE", "BETA", "ALPHA"}:
        raise ValueError("PAPER_CHANNEL must be STABLE, BETA, or ALPHA")
    builds = request_json(f"{PAPER_API}/projects/paper/versions/{urllib.parse.quote(version, safe='.')}/builds")
    if isinstance(builds, dict) and builds.get("ok") is False:
        raise RuntimeError(builds.get("message", "PaperMC rejected that version"))
    candidates = [item for item in builds if item.get("channel", "").upper() == channel]
    if not candidates:
        available = sorted({str(item.get("channel", "unknown")) for item in builds}) if isinstance(builds, list) else []
        more = f" Available channels: {', '.join(available)}." if available else ""
        raise RuntimeError(f"No {channel} Paper build is available for Minecraft {version}.{more} Choose a version with a stable build or explicitly set PAPER_CHANNEL=ALPHA in native/config.json.")
    selected = candidates[0]
    download = selected.get("downloads", {}).get("server:default", {})
    if not download.get("url") or not download.get("checksums", {}).get("sha256"):
        raise RuntimeError("PaperMC build response did not include a verified server JAR download.")
    return {"version": version, "build": selected.get("id"), "url": download["url"],
            "sha256": download["checksums"]["sha256"], "name": download.get("name", f"paper-{version}.jar"),
            "channel": channel}


def _read_native_config() -> dict[str, Any]:
    if not NATIVE_CONFIG.exists():
        return {"memory": "1G", "paper_channel": "STABLE", "panel_port": 8080}
    try:
        data = json.loads(NATIVE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {NATIVE_CONFIG}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _write_native_config(config: dict[str, Any]) -> None:
    NATIVE.mkdir(parents=True, exist_ok=True)
    temp = NATIVE_CONFIG.with_suffix(".json.tmp")
    temp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temp.replace(NATIVE_CONFIG)


def _tail_log(path: Path, max_bytes: int = 262144, lines: int = 300) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        data = stream.read(max_bytes)
    return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])


def _ensure_eula() -> None:
    env_path = ROOT / ".env"
    env = parse_env_file(env_path)
    if env.get("EULA", "FALSE").upper() == "TRUE":
        (DATA / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        return
    print("Read and accept the Minecraft EULA before running the server: https://aka.ms/MinecraftEULA")
    if not sys.stdin.isatty():
        raise RuntimeError("EULA is not accepted. Run bash termux-run.sh in an interactive Termux session and type yes.")
    answer = input("Do you accept the Minecraft EULA? Type yes to continue: ").strip().lower()
    if answer != "yes":
        raise RuntimeError("EULA was not accepted; server will not start.")
    update_env_file(env_path, {"EULA": "TRUE"})
    (DATA / "eula.txt").write_text("eula=true\n", encoding="utf-8")


def _ensure_config_link() -> None:
    """Use the Docker-mounted Paper config directory when no native data/config exists."""
    shared = ROOT / "config"
    local = DATA / "config"
    shared.mkdir(parents=True, exist_ok=True)
    if local.is_symlink():
        return
    if local.exists():
        if local.is_dir() and not any(local.iterdir()):
            local.rmdir()
        else:
            print(f"Warning: keeping existing {local}; it is not being replaced with the Docker-shared config folder.")
            return
    local.symlink_to(Path("../config"), target_is_directory=True)


def _properties_file(settings: dict[str, str]) -> None:
    path = DATA / "server.properties"
    update = {
        "level-name": settings.get("WORLD_NAME", "SurvivalSMP"),
        "level-seed": settings.get("SEED", "399918057248930"),
        "server-port": settings.get("JAVA_PORT", "25565"),
        "max-players": settings.get("MAX_PLAYERS", "20"),
        "view-distance": settings.get("VIEW_DISTANCE", "8"),
        "simulation-distance": settings.get("SIMULATION_DISTANCE", "6"),
        "difficulty": settings.get("DIFFICULTY", "hard"),
        "motd": settings.get("MOTD", "A self-hosted Minecraft server").replace("\n", " ").replace("\r", " "),
        "pvp": settings.get("PVP", "true").lower(),
        "white-list": settings.get("ENABLE_WHITELIST", "false").lower(),
        "online-mode": "true",
        "enable-rcon": "false",
    }
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    output: list[str] = []
    written: set[str] = set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in update:
            output.append(f"{key}={update[key]}")
            written.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in update.items() if key not in written)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _set_geyser_port(path: Path, port: int) -> bool:
    """Update only bedrock.port in an existing Geyser config, preserving other YAML lines."""
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    section_start = None
    section_indent = 0
    section_end = len(lines)
    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)bedrock\s*:\s*(?:#.*)?$", line)
        if match:
            section_start = i
            section_indent = len(match.group(1))
            if section_indent != 0:
                section_start = None
            continue
        if section_start is not None and line.strip() and not line.lstrip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            if indent <= section_indent:
                section_end = i
                break
    if section_start is None:
        return False
    changed = False
    port_line = re.compile(r"^(\s*port\s*:\s*)[^#]*(#.*)?$")
    for i in range(section_start + 1, section_end):
        match = port_line.match(lines[i])
        indent = len(lines[i]) - len(lines[i].lstrip())
        if match and indent == section_indent + 2:
            replacement = f"{match.group(1)}{port}"
            if match.group(2):
                replacement += " " + match.group(2).lstrip()
            changed = lines[i] != replacement
            lines[i] = replacement
            break
    else:
        lines.insert(section_start + 1, " " * (section_indent + 2) + f"port: {port}")
        changed = True
    if changed:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp.replace(path)
    return changed


def _download_plugins(settings: dict[str, str], version: str) -> None:
    urls = [u.strip() for u in settings.get("PLUGINS", "").split(",") if u.strip()]
    plugin_dir = DATA / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls, start=1):
        # AxGraves' current artifact requires Paper 1.20.2 or newer.
        if "Cz6msz34" in url and version.startswith("1."):
            parts = tuple(int(p) for p in version.split("."))
            if parts < (1, 20, 2):
                print(f"Skipping AxGraves: this preset targets Paper 1.20.2+ (selected {version}).")
                continue
        parsed_name = Path(urllib.parse.urlparse(url).path).name
        if parsed_name.endswith(".jar"):
            target_name = parsed_name
        else:
            target_name = f"downloaded-plugin-{index}.jar"
        target = plugin_dir / target_name
        if target.exists() and target.stat().st_size:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as response:
                suggested = response.headers.get_filename()
                if suggested and suggested.lower().endswith(".jar"):
                    target = plugin_dir / Path(suggested).name
                content_type = response.headers.get("Content-Type", "")
                temp = target.with_name(target.name + ".download")
                with temp.open("wb") as output:
                    shutil.copyfileobj(response, output)
            if temp.stat().st_size < 1024:
                temp.unlink(missing_ok=True)
                raise RuntimeError("download was empty or unexpectedly small")
            temp.replace(target)
            print(f"Plugin downloaded: {target.name}")
        except Exception as exc:
            print(f"Warning: plugin download failed for {url}: {exc}. Server can still start; add a compatible JAR in data/plugins.")


class NativeServer:
    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.lock = threading.RLock()
        self.log_lock = threading.Lock()
        self.last_error = ""
        self.stop_event = threading.Event()
        self.settings_path = ROOT / ".env"

    def settings(self) -> dict[str, str]:
        raw = parse_env_file(self.settings_path)
        raw.setdefault("WORLD_NAME", "SurvivalSMP")
        raw.setdefault("SEED", "399918057248930")
        raw.setdefault("SERVER_ADDRESS", "survivalsmp.vy")
        native = _read_native_config()
        # Do not use Docker's generic 4G default on a phone; Termux has an isolated 1G default.
        raw["TERMUX_MEMORY"] = str(native.get("memory", raw.get("TERMUX_MEMORY", "1G")))
        raw["PAPER_CHANNEL"] = str(native.get("paper_channel", "STABLE"))
        raw["PANEL_PORT"] = str(native.get("panel_port", "8080"))
        raw["SERVER_TYPE"] = raw.get("SERVER_TYPE", "PAPER").upper()
        return validate_server_settings(raw)

    def check_host(self, settings: dict[str, str]) -> tuple[str, int]:
        if not is_termux():
            raise RuntimeError("Native runtime is Termux-only. On desktop Linux use the unchanged Docker command: ./run.sh")
        arch = normalize_arch(platform.machine())
        if arch != "aarch64":
            raise RuntimeError(f"Native Termux runtime currently supports ARM64 only; detected {arch}.")
        if settings["SERVER_TYPE"] != "PAPER":
            raise RuntimeError("Native Termux mode currently supports Paper only. Fabric/Forge/NeoForge and Vanilla remain Docker mode options.")
        version = settings["MINECRAFT_VERSION"]
        if version == "LATEST":
            version = resolve_paper_version(version)
        required = required_java_for_paper(version)
        java = shutil.which("java")
        if not java:
            raise RuntimeError("Java is missing. Run bash install-termux.sh to install OpenJDK 25.")
        result = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=10)
        major = java_major_from_version(result.stderr + result.stdout)
        if major < required:
            raise RuntimeError(f"Paper {version} recommends Java {required}; this Termux Java is {major}. Run bash install-termux.sh and select a compatible runtime.")
        return version, major

    def _ensure_server_jar(self, version: str, update: bool = False, channel: str = "STABLE") -> Path:
        DATA.mkdir(parents=True, exist_ok=True)
        jar = DATA / "paper.jar"
        docker_jar = DATA / "server.jar"
        old_state: dict[str, Any] = {}
        if STATE_FILE.exists():
            try:
                old_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                old_state = {}
        if jar.exists() and not update:
            if not old_state or old_state.get("version") == version:
                if not old_state:
                    print("Using existing data/paper.jar (no native version metadata); it will not be overwritten.")
                return jar
            raise RuntimeError(f"data/paper.jar is recorded for Paper {old_state.get('version')}, requested {version}. Back up the entire data/ directory, then rerun `bash termux-run.sh --update` to replace the server JAR. World data is never deleted automatically.")
        if docker_jar.exists() and not update and not jar.exists():
            print("Using existing data/server.jar from the Docker Paper deployment; it will not be overwritten.")
            return docker_jar
        world_paths = [DATA / name for name in ("world", "world_nether", "world_the_end", "worlds")]
        has_world = any(path.exists() and (not path.is_dir() or any(path.iterdir())) for path in world_paths)
        if has_world and not jar.exists() and not docker_jar.exists() and not update:
            raise RuntimeError("Existing world data was found but no known Paper JAR is present. Back up the entire data/ directory, then rerun `bash termux-run.sh --update` and confirm the world backup before downloading Paper.")
        build = get_paper_build(version, channel)
        print(f"Downloading Paper {version}, build {build['build']} ({channel})…")
        temp_jar = DATA / "paper.jar.new"
        digest = download_file(build["url"], temp_jar, build["sha256"])
        if jar.exists():
            backups = DATA / "server-jar-backups"
            backups.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = backups / f"paper-{old_state.get('version', 'unknown')}-{stamp}.jar"
            shutil.copy2(jar, backup)
            print(f"Previous server JAR backed up at {backup}. World data is unchanged; restore your full world backup if an upgrade is incompatible.")
        temp_jar.replace(jar)
        STATE_FILE.write_text(json.dumps({"version": version, "build": build["build"], "channel": channel,
                                          "sha256": digest, "downloaded_at": datetime.now().isoformat()}, indent=2) + "\n",
                              encoding="utf-8")
        return jar

    def start(self, update: bool = False) -> dict[str, Any]:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return {"ok": True, "message": "Server is already running."}
            try:
                settings = self.settings()
                version, java_major = self.check_host(settings)
                _ensure_eula()
                _ensure_config_link()
                channel = settings.get("PAPER_CHANNEL", "STABLE")
                server_jar = self._ensure_server_jar(version, update=update, channel=channel)
                _download_plugins(settings, version)
                _properties_file(settings)
                for geyser_config in DATA.glob("plugins/Geyser*/config.yml"):
                    _set_geyser_port(geyser_config, int(settings["BEDROCK_PORT"]))
                memory = settings["TERMUX_MEMORY"]
                args = build_java_args(shutil.which("java") or "java", server_jar, memory)
                args[-1:] = ["--nogui"]
                self.last_error = ""
                self.stop_event.clear()
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                log = LOG_FILE.open("a", encoding="utf-8", buffering=1)
                self.proc = subprocess.Popen(args, cwd=DATA, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, bufsize=1)
                threading.Thread(target=self._pump_output, args=(self.proc, log), daemon=True).start()
                timer = threading.Timer(3.0, self._configure_geyser_after_start,
                                        args=(int(settings["BEDROCK_PORT"]), 15))
                timer.daemon = True
                timer.start()
                print(f"Starting Paper {version} with Java {java_major}, max heap {memory}; PID {self.proc.pid}.")
                return {"ok": True, "message": f"Starting Paper {version} (Java {java_major}, {memory} heap).", "pid": self.proc.pid}
            except Exception as exc:
                self.last_error = str(exc)
                print(f"Start failed: {exc}", file=sys.stderr)
                return {"ok": False, "error": self.last_error}

    def _pump_output(self, proc: subprocess.Popen[str], log: Any) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                with self.log_lock:
                    log.write(line)
                    log.flush()
                    sys.stdout.write(line)
                    sys.stdout.flush()
        except Exception as exc:
            with self.log_lock:
                log.write(f"[log capture error] {exc}\n")
        finally:
            log.close()
            with self.lock:
                if self.proc is proc:
                    code = proc.poll()
                    if code not in (None, 0) and not self.stop_event.is_set():
                        self.last_error = f"Java server exited with code {code}; see logs/native-server.log."
                    self.proc = None

    def command(self, text: str) -> None:
        if not text or len(text) > 300 or "\n" in text or "\r" in text:
            raise ValueError("Enter one server command, up to 300 characters.")
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                raise RuntimeError("Server is not running.")
            proc.stdin.write(text.strip() + "\n")
            proc.stdin.flush()

    def _configure_geyser_after_start(self, port: int, retries: int) -> None:
        with self.lock:
            proc = self.proc
            running = proc is not None and proc.poll() is None
        if not running:
            return
        found = False
        changed = False
        for config in DATA.glob("plugins/Geyser*/config.yml"):
            found = True
            changed = _set_geyser_port(config, port) or changed
        if changed:
            try:
                self.command("geyser reload")
                print(f"Set Geyser Bedrock port to UDP {port} and reloaded its config.")
            except Exception as exc:
                print(f"Geyser config saved for UDP {port}; reload it from console if needed: {exc}")
        elif not found and retries > 0:
            timer = threading.Timer(2.0, self._configure_geyser_after_start, args=(port, retries - 1))
            timer.daemon = True
            timer.start()

    def stop(self, graceful_timeout: int = 60) -> dict[str, Any]:
        with self.lock:
            proc = self.proc
            if proc is None or proc.poll() is not None:
                self.proc = None
                return {"ok": True, "message": "Server is already stopped."}
            self.stop_event.set()
        message = stop_process(proc, graceful_timeout=graceful_timeout)
        if "fallback" in message or "last resort" in message:
            print(message, file=sys.stderr)
        with self.lock:
            if self.proc is proc:
                self.proc = None
        return {"ok": True, "message": message}

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def status(self) -> dict[str, Any]:
        with self.lock:
            proc = self.proc
            running = proc is not None and proc.poll() is None
            pid = proc.pid if running and proc else None
        rss = None
        if pid:
            status_path = Path(f"/proc/{pid}/status")
            if status_path.exists():
                match = re.search(r"(?m)^VmRSS:\s+(\d+)\s+kB", status_path.read_text(errors="replace"))
                if match:
                    rss = int(match.group(1)) // 1024
        settings = self.settings()
        java = shutil.which("java")
        java_major = None
        if java:
            try:
                version_result = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=5)
                java_major = java_major_from_version(version_result.stderr + version_result.stdout)
            except Exception:
                pass
        try:
            log_tail = _tail_log(LOG_FILE)
        except OSError:
            log_tail = ""
        state = {}
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not state:
            state = {"version": settings.get("MINECRAFT_VERSION", "LATEST"),
                     "source": "existing server.jar" if (DATA / "server.jar").exists() else "configured"}
        return {"running": running, "pid": pid, "rss_mb": rss, "last_error": self.last_error,
                "log": log_tail, "settings": settings, "server": state,
                "java": java, "java_major": java_major, "arch": normalize_arch(platform.machine())}

    def update_settings(self, updates: dict[str, Any]) -> dict[str, str]:
        allowed = {"WORLD_NAME", "SEED", "SERVER_ADDRESS", "JAVA_PORT", "BEDROCK_PORT", "MAX_PLAYERS", "VIEW_DISTANCE", "SIMULATION_DISTANCE", "DIFFICULTY", "PVP", "ENABLE_WHITELIST", "MOTD"}
        shared = {key: str(value).strip() for key, value in updates.items() if key in allowed}
        if "MOTD" in shared and (len(shared["MOTD"]) > 120 or "\n" in shared["MOTD"] or "\r" in shared["MOTD"]):
            raise ValueError("MOTD must be a single line of at most 120 characters.")
        for key in ("PVP", "ENABLE_WHITELIST"):
            if key in shared and shared[key].lower() not in {"true", "false"}:
                raise ValueError(f"{key} must be true or false.")
        if "DIFFICULTY" in shared and shared["DIFFICULTY"].lower() not in {"peaceful", "easy", "normal", "hard"}:
            raise ValueError("DIFFICULTY must be peaceful, easy, normal, or hard.")
        for key, low, high in (("MAX_PLAYERS", 1, 1000), ("VIEW_DISTANCE", 2, 32), ("SIMULATION_DISTANCE", 2, 32)):
            if key in shared:
                try:
                    number = int(shared[key])
                except ValueError as exc:
                    raise ValueError(f"{key} must be numeric.") from exc
                if not low <= number <= high:
                    raise ValueError(f"{key} must be between {low} and {high}.")
                shared[key] = str(number)
        if "JAVA_PORT" in shared:
            shared["JAVA_PORT"] = str(validate_port(shared["JAVA_PORT"]))
        if "BEDROCK_PORT" in shared:
            shared["BEDROCK_PORT"] = str(validate_port(shared["BEDROCK_PORT"]))
        native = _read_native_config()
        if "TERMUX_MEMORY" in updates or "MEMORY" in updates:
            memory = str(updates.get("TERMUX_MEMORY", updates.get("MEMORY", ""))).strip().upper()
            parse_memory_mb(memory)
            native["memory"] = memory
        if "PANEL_PORT" in updates:
            native["panel_port"] = validate_port(updates["PANEL_PORT"])
        # Do not let the web panel change Minecraft version while running; that requires an explicit terminal-side update flow.
        if "MINECRAFT_VERSION" in updates:
            version = str(updates["MINECRAFT_VERSION"]).strip()
            if not re.fullmatch(r"(?:LATEST|\d+\.\d+(?:\.\d+)?)", version, re.IGNORECASE):
                raise ValueError("Enter LATEST or a dotted Minecraft release version.")
            if self.status()["running"]:
                raise ValueError("Stop the server first. To change versions, edit MINECRAFT_VERSION in .env, back up data/, then rerun `bash termux-run.sh --update` in the terminal.")
            shared["MINECRAFT_VERSION"] = version
        # Validate using the same constraints as the launcher.
        prospective = self.settings()
        prospective.update(shared)
        prospective["TERMUX_MEMORY"] = native.get("memory", prospective.get("TERMUX_MEMORY", "1G"))
        validate_server_settings(prospective)
        if shared:
            update_env_file(self.settings_path, shared)
        if native:
            _write_native_config(native)
        return {**shared, "TERMUX_MEMORY": str(native.get("memory", self.settings()["TERMUX_MEMORY"]))}


MANAGER = NativeServer()


class Handler(BaseHTTPRequestHandler):
    server_version = "MinecraftServerKitNative/0.2"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[panel] " + fmt % args)

    def _origin_ok(self) -> bool:
        host = self.headers.get("Host", "")
        if host not in {"localhost", "127.0.0.1", "[::1]", f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in {f"http://localhost:{self.server.server_port}", f"http://127.0.0.1:{self.server.server_port}"}

    def _json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = (NATIVE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            try:
                self._json(MANAGER.status())
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
        elif self.path == "/health":
            self._json({"ok": True})
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._origin_ok():
            self._json({"error": "Requests are accepted only from the local panel."}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                raise ValueError("Request body is empty or too large.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/action":
                action = body.get("action")
                if action == "start":
                    result = MANAGER.start()
                elif action == "stop":
                    result = MANAGER.stop()
                elif action == "restart":
                    result = MANAGER.restart()
                else:
                    self._json({"error": "Unknown action"}, 400)
                    return
                self._json(result, 200 if result.get("ok") else 503)
            elif self.path == "/api/command":
                MANAGER.command(str(body.get("command", "")))
                self._json({"ok": True, "message": "Command sent to the local server console."})
            elif self.path == "/api/settings":
                result = MANAGER.update_settings(body)
                self._json({"ok": True, "settings": result, "message": "Settings saved. Restart Paper to apply them."})
            else:
                self._json({"error": "Not found"}, 404)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_PUT(self) -> None:  # noqa: N802
        self.do_POST()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="replace the Paper JAR after a verified download; prompts for a world-backup confirmation")
    args = parser.parse_args()
    if not is_termux():
        print("This native runtime is for Termux on Android ARM64. Use ./run.sh for Docker-based Linux.", file=sys.stderr)
        return 2
    if normalize_arch(platform.machine()) != "aarch64":
        print(f"Android ARM64 is required; detected {platform.machine()}.", file=sys.stderr)
        return 2
    world_paths = [DATA / name for name in ("world", "world_nether", "world_the_end", "worlds")]
    existing_world = any(path.exists() and (not path.is_dir() or any(path.iterdir())) for path in world_paths)
    if args.update and ((DATA / "paper.jar").exists() or (DATA / "server.jar").exists() or existing_world):
        print("Starting/updating Paper against existing files can migrate worlds and may be irreversible. Back up the entire data/ directory first.")
        confirmation = input("Type I HAVE A WORLD BACKUP to continue (no world files are deleted): ").strip()
        if confirmation != "I HAVE A WORLD BACKUP":
            print("Update cancelled; existing server JAR and world were not changed.")
            return 1
    result = MANAGER.start(update=args.update)
    if not result.get("ok"):
        return 1
    port = MANAGER.settings().get("PANEL_PORT", "8080")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    except OSError as exc:
        MANAGER.stop()
        print(f"Could not start local panel on 127.0.0.1:{port}: {exc}", file=sys.stderr)
        return 1
    server.daemon_threads = True
    print(f"Native control page: http://127.0.0.1:{port}")
    print("Server logs are shown here and saved to logs/native-server.log. Press Ctrl+C to save and stop the server.")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping the native server…")
    finally:
        server.server_close()
        MANAGER.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
