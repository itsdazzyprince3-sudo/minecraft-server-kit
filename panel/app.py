import os
import re
import subprocess
from pathlib import Path
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename
from mcrcon import MCRcon

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024
PROJECT = Path(os.getenv("PROJECT_DIR", "/project"))
DATA = Path(os.getenv("DATA_DIR", "/data"))
ENV_FILE = PROJECT / ".env"
CONTAINER = os.getenv("SERVER_CONTAINER", "mc-server")

ALLOWED_SETTINGS = {
    "SERVER_TYPE", "MINECRAFT_VERSION", "MEMORY", "MAX_PLAYERS",
    "VIEW_DISTANCE", "SIMULATION_DISTANCE", "DIFFICULTY", "PVP",
    "ENABLE_WHITELIST", "ENFORCE_WHITELIST", "JAVA_PORT", "BEDROCK_PORT",
    "PANEL_PORT", "MOTD", "SPAWN_PROTECTION"
}


def docker(*args, timeout=15):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Docker command failed").strip())
    return result.stdout.strip()


def get_env():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def write_env(updates):
    old = get_env()
    old.update(updates)
    # Preserve the RCON secret and plugin download list; never expose them in the page/API.
    lines = ["# Local server settings. Do not commit this file."]
    for key, value in old.items():
        if re.fullmatch(r"[A-Z_]+", key):
            safe = str(value).replace("\n", " ").replace("\r", " ")
            lines.append(f"{key}={safe}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def server_state():
    try:
        raw = docker("inspect", "-f", "{{.State.Status}}|{{.State.Health.Status}}", CONTAINER)
        status, _, health = raw.partition("|")
        return {"status": status, "health": health or "unknown"}
    except Exception as e:
        return {"status": "not-created", "health": "unknown", "error": str(e)}


def rcon(command):
    with MCRcon(os.getenv("RCON_HOST", "minecraft"), os.getenv("RCON_PASSWORD", ""),
                port=int(os.getenv("RCON_PORT", "25575")), timeout=8) as client:
        return client.command(command)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    state = server_state()
    try:
        state["logs"] = docker("logs", "--tail", "250", CONTAINER, timeout=10)
    except Exception as e:
        state["logs"] = str(e)
    try:
        state["players"] = rcon("list")
    except Exception:
        state["players"] = "RCON not ready yet"
    state["config"] = {k: v for k, v in get_env().items() if k in ALLOWED_SETTINGS}
    return jsonify(state)


@app.post("/api/command")
def command():
    body = request.get_json(silent=True) or {}
    cmd = str(body.get("command", "")).strip()
    if not cmd or len(cmd) > 300 or "\n" in cmd or "\r" in cmd:
        return jsonify(error="Enter one Minecraft command, up to 300 characters."), 400
    try:
        return jsonify(output=rcon(cmd))
    except Exception as e:
        return jsonify(error=str(e)), 503


@app.post("/api/action")
def action():
    body = request.get_json(silent=True) or {}
    action_name = body.get("action")
    try:
        if action_name == "restart":
            docker("restart", CONTAINER, timeout=90)
        elif action_name == "stop":
            docker("stop", "-t", "60", CONTAINER, timeout=90)
        elif action_name == "start":
            docker("start", CONTAINER)
        else:
            return jsonify(error="Unknown action"), 400
        return jsonify(ok=True, action=action_name)
    except Exception as e:
        return jsonify(error=str(e)), 503


@app.put("/api/settings")
def settings():
    body = request.get_json(silent=True) or {}
    updates = {}
    for key, value in body.items():
        if key not in ALLOWED_SETTINGS:
            continue
        value = str(value).strip()
        if len(value) > 120 or "\n" in value or "\r" in value:
            return jsonify(error=f"Invalid value for {key}"), 400
        if key == "SERVER_TYPE" and value.upper() not in {"PAPER", "FABRIC", "FORGE", "NEOFORGE", "VANILLA"}:
            return jsonify(error="Server type must be PAPER, FABRIC, FORGE, NEOFORGE, or VANILLA."), 400
        if key in {"JAVA_PORT", "BEDROCK_PORT", "PANEL_PORT", "MAX_PLAYERS", "VIEW_DISTANCE", "SIMULATION_DISTANCE", "SPAWN_PROTECTION"}:
            try:
                n = int(value)
                if n < 0 or n > 65535:
                    raise ValueError()
            except ValueError:
                return jsonify(error=f"{key} must be a valid number."), 400
        if key in {"PVP", "ENABLE_WHITELIST", "ENFORCE_WHITELIST"} and value.lower() not in {"true", "false"}:
            return jsonify(error=f"{key} must be true or false."), 400
        updates[key] = value.upper() if key == "SERVER_TYPE" else value
    if not updates:
        return jsonify(error="No supported settings supplied."), 400
    try:
        write_env(updates)
        # Recreate only the game server to apply environment changes; the panel stays online.
        output = docker("compose", "--project-name", "mcstack", "--project-directory", str(PROJECT), "--env-file", str(ENV_FILE),
                        "-f", str(PROJECT / "docker-compose.yml"), "up", "-d", "--force-recreate", "minecraft", timeout=180)
        return jsonify(ok=True, message="Saved settings and recreated the Minecraft container.", output=output)
    except Exception as e:
        return jsonify(error=f"Settings saved, but applying them failed: {e}"), 503


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="Choose a .jar file."), 400
    filename = secure_filename(f.filename)
    if not filename.lower().endswith(".jar"):
        return jsonify(error="Only .jar files are accepted."), 400
    server_type = get_env().get("SERVER_TYPE", "PAPER").upper()
    dest_folder = "plugins" if server_type == "PAPER" else "mods"
    dest = DATA / dest_folder
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / filename
    f.save(target)
    return jsonify(ok=True, message=f"Uploaded {filename} to data/{dest_folder}. Restart the server to load it.", folder=dest_folder)


@app.get("/api/files")
def files():
    result = {}
    for folder in ("plugins", "mods"):
        path = DATA / folder
        result[folder] = sorted(p.name for p in path.iterdir() if p.is_file()) if path.exists() else []
    return jsonify(result)


@app.get("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    # Compose binds this service to 127.0.0.1 on the host. Do not publish port 8080 externally.
    app.run(host="0.0.0.0", port=8080)
