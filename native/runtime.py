"""Shared, testable helpers for the native Termux Paper runtime."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

VERSION_RE = re.compile(r"^(?:LATEST|\d+\.\d+(?:\.\d+)?)$", re.IGNORECASE)
MEMORY_RE = re.compile(r"^(\d+)([MG])$", re.IGNORECASE)


def is_termux(env: Mapping[str, str] | None = None, prefix: str | None = None) -> bool:
    env = env if env is not None else os.environ
    prefix = prefix if prefix is not None else env.get("PREFIX", "")
    return bool(env.get("TERMUX_VERSION")) or "/com.termux/files/usr" in prefix


def normalize_arch(machine: str) -> str:
    value = machine.strip().lower()
    if value in {"aarch64", "arm64"}:
        return "aarch64"
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"armv7l", "armv8l"}:
        return "armv7"
    return value or "unknown"


def java_major_from_version(text: str) -> int:
    """Parse `java -version` output for modern and legacy Java version syntax."""
    match = re.search(r'(?i)version\s+"?([0-9]+)(?:\.([0-9]+))?', text)
    if not match:
        match = re.search(r"(?m)^\s*(?:openjdk|java)\s+([0-9]+)(?:\.([0-9]+))?", text)
    if not match:
        raise ValueError("Could not parse Java version output")
    first = int(match.group(1))
    second = int(match.group(2) or 0)
    return second if first == 1 else first


def select_java_runtime(required_major: int, default_java: str | None, prefix: str | None = None) -> tuple[str, int]:
    """Prefer an installed versioned JDK matching Paper, even if Termux's `java` points elsewhere."""
    candidates: list[Path] = []
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home:
        candidates.append(Path(java_home) / "bin" / "java")
    prefix = prefix if prefix is not None else os.environ.get("PREFIX", "")
    if prefix:
        candidates.extend(sorted((Path(prefix) / "lib" / "jvm").glob("java-*-openjdk/bin/java")))
    if default_java:
        candidates.append(Path(default_java))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen and candidate.is_file() and os.access(candidate, os.X_OK):
            seen.add(key)
            unique.append(candidate)
    detected: list[tuple[Path, int]] = []
    for candidate in unique:
        try:
            result = subprocess.run([str(candidate), "-version"], capture_output=True, text=True, timeout=8)
            major = java_major_from_version(result.stderr + result.stdout)
            detected.append((candidate, major))
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    exact = [(path, major) for path, major in detected if major == required_major]
    compatible = exact or sorted(
        ((path, major) for path, major in detected if major > required_major),
        key=lambda item: item[1],
    )
    if compatible:
        path, major = compatible[0]
        return str(path), major
    found = ", ".join(f"Java {major} at {path}" for path, major in detected) or "no runnable Java binaries"
    raise ValueError(f"Paper requires Java {required_major}; found {found}.")


def _version_tuple(value: str) -> tuple[int, ...]:
    if not VERSION_RE.fullmatch(value) or value.upper() == "LATEST":
        raise ValueError(f"Invalid Minecraft version: {value!r}")
    return tuple(int(x) for x in value.split("."))


def required_java_for_paper(version: str) -> int:
    """PaperMC's published recommended Java matrix, expressed as a minimum major."""
    v = _version_tuple(version)
    if v[0] >= 26:
        if v < (26, 1):
            raise ValueError(f"Unsupported Paper version: {version}")
        return 25
    if v[0] == 1:
        if (1, 20) <= v <= (1, 21, 11):
            return 21
        if (1, 17) <= v <= (1, 19, 99):
            return 17
        if v == (1, 16, 5):
            return 16
        if (1, 12) <= v <= (1, 16, 4):
            return 11
        if (1, 7, 10) <= v <= (1, 11, 99):
            return 8
    raise ValueError(f"No supported Paper Java mapping is defined for {version}")


def parse_memory_mb(value: str) -> int:
    match = MEMORY_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("Memory must look like 768M, 1G, or 2G")
    amount = int(match.group(1))
    unit = match.group(2).upper()
    mb = amount if unit == "M" else amount * 1024
    if mb < 512 or mb > 65536:
        raise ValueError("Native server memory must be between 512M and 64G")
    return mb


def validate_port(value: str | int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Port must be a number") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    return port


def parse_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=value files without sourcing or executing shell content."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            values[key] = value.strip()
    return values


def update_env_file(path: Path, updates: Mapping[str, str]) -> None:
    """Atomically update selected values while retaining unrelated Docker settings."""
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def build_java_args(java: str, jar: str | Path, memory: str) -> list[str]:
    max_mb = parse_memory_mb(memory)
    initial_mb = min(512, max(256, max_mb // 2))
    return [java, f"-Xms{initial_mb}M", f"-Xmx{memory.upper()}", "-jar", str(jar), "--nogui"]


def stop_process(proc: object, graceful_timeout: int = 60, terminate_timeout: int = 10) -> str:
    """Ask Paper to save/stop first; signal only if it does not exit in time."""
    if proc.poll() is not None:  # type: ignore[attr-defined]
        return "Server is already stopped."
    try:
        stdin = proc.stdin  # type: ignore[attr-defined]
        if stdin:
            stdin.write("stop\n")
            stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        proc.wait(timeout=graceful_timeout)  # type: ignore[attr-defined]
        return "Server stopped gracefully."
    except subprocess.TimeoutExpired:
        proc.terminate()  # type: ignore[attr-defined]
        try:
            proc.wait(timeout=terminate_timeout)  # type: ignore[attr-defined]
            return "Server stopped after SIGTERM fallback."
        except subprocess.TimeoutExpired:
            proc.kill()  # type: ignore[attr-defined]
            proc.wait(timeout=5)  # type: ignore[attr-defined]
            return "Server was force-stopped as a last resort; inspect logs and world backups."


def validate_server_settings(settings: Mapping[str, str]) -> dict[str, str]:
    result = dict(settings)
    version = result.get("MINECRAFT_VERSION", "LATEST").strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("Minecraft version must be LATEST or a dotted release such as 26.3")
    result["MINECRAFT_VERSION"] = version.upper() if version.lower() == "latest" else version
    result["JAVA_PORT"] = str(validate_port(result.get("JAVA_PORT", "25565")))
    result["BEDROCK_PORT"] = str(validate_port(result.get("BEDROCK_PORT", "19132")))
    world_name = result.get("WORLD_NAME", "SurvivalSMP").strip()
    if not re.fullmatch(r"[A-Za-z0-9 _-]{1,64}", world_name) or world_name in {".", ".."}:
        raise ValueError("WORLD_NAME must be 1–64 letters, digits, spaces, underscores, or hyphens; path separators are not allowed.")
    result["WORLD_NAME"] = world_name
    seed = result.get("SEED", "399918057248930").strip()
    if not re.fullmatch(r"-?\d{1,20}", seed) or not -(2**63) <= int(seed) <= 2**63 - 1:
        raise ValueError("SEED must be a signed 64-bit integer.")
    result["SEED"] = seed
    address = result.get("SERVER_ADDRESS", "localhost").strip()
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if len(address) > 253 or (address.lower() != "localhost" and not re.fullmatch(label + r"(?:\." + label + r")+", address)):
        raise ValueError("SERVER_ADDRESS must be localhost or a hostname such as survivalsmp.example.com; it is display-only and does not configure DNS.")
    result["SERVER_ADDRESS"] = address
    result["MEMORY"] = result.get("TERMUX_MEMORY", result.get("MEMORY", "1G"))
    parse_memory_mb(result["MEMORY"])
    if "MAX_PLAYERS" in result:
        n = int(result["MAX_PLAYERS"])
        if not 1 <= n <= 1000:
            raise ValueError("MAX_PLAYERS must be between 1 and 1000")
    for key in ("VIEW_DISTANCE", "SIMULATION_DISTANCE"):
        if key in result:
            n = int(result[key])
            if not 2 <= n <= 32:
                raise ValueError(f"{key} must be between 2 and 32")
    return result
