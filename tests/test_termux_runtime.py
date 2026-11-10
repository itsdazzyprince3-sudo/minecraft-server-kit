import io
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native"))
from runtime import (  # noqa: E402
    build_java_args,
    is_termux,
    java_major_from_version,
    normalize_arch,
    parse_env_file,
    parse_memory_mb,
    required_java_for_paper,
    select_java_runtime,
    stop_process,
    update_env_file,
    validate_port,
    validate_server_settings,
)
from manager import _local_ipv4, _properties_file, _set_geyser_port  # noqa: E402


class RuntimeDetectionTests(unittest.TestCase):
    def test_detects_termux_markers(self):
        self.assertTrue(is_termux({"TERMUX_VERSION": "0.118"}, ""))
        self.assertTrue(is_termux({}, "/data/data/com.termux/files/usr"))
        self.assertFalse(is_termux({}, "/usr"))

    def test_normalizes_architecture(self):
        self.assertEqual(normalize_arch("aarch64"), "aarch64")
        self.assertEqual(normalize_arch("arm64"), "aarch64")
        self.assertEqual(normalize_arch("x86_64"), "x86_64")

    def test_parses_java_versions(self):
        self.assertEqual(java_major_from_version('openjdk version "25.0.1" 2026-04-21'), 25)
        self.assertEqual(java_major_from_version('openjdk version "21.0.12.1" 2026-08-18'), 21)
        self.assertEqual(java_major_from_version('java version "1.8.0_392"'), 8)
        with self.assertRaises(ValueError):
            java_major_from_version("not Java")

    def test_paper_java_matrix(self):
        self.assertEqual(required_java_for_paper("26.3"), 25)
        self.assertEqual(required_java_for_paper("1.21.11"), 21)
        self.assertEqual(required_java_for_paper("1.19.4"), 17)
        self.assertEqual(required_java_for_paper("1.16.5"), 16)
        self.assertEqual(required_java_for_paper("1.16.4"), 11)
        self.assertEqual(required_java_for_paper("1.11.2"), 8)
        with self.assertRaises(ValueError):
            required_java_for_paper("not-a-version")

    def test_selects_installed_exact_jdk_over_default_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "usr"
            binaries = {}
            for major in (21, 25):
                binary = prefix / "lib" / "jvm" / f"java-{major}-openjdk" / "bin" / "java"
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text(f'#!/bin/sh\necho \'openjdk version "{major}.0.1"\' >&2\n')
                binary.chmod(0o755)
                binaries[major] = binary
            selected, major = select_java_runtime(25, str(binaries[21]), str(prefix))
            self.assertEqual(Path(selected), binaries[25])
            self.assertEqual(major, 25)
            selected, major = select_java_runtime(21, str(binaries[25]), str(prefix))
            self.assertEqual(Path(selected), binaries[21])
            self.assertEqual(major, 21)

    def test_local_address_uses_wifi_not_vpn_interface(self):
        output = "\n".join((
            "7: tun0 inet 192.0.0.2/32 scope global tun0",
            "8: wlan0 inet 192.168.1.77/24 brd 192.168.1.255 scope global wlan0",
        ))
        result = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
        with patch("manager.subprocess.run", return_value=result):
            self.assertEqual(_local_ipv4(), "192.168.1.77")


class ConfigAndArgumentsTests(unittest.TestCase):
    def test_memory_and_ports_are_bounded(self):
        self.assertEqual(parse_memory_mb("1G"), 1024)
        self.assertEqual(parse_memory_mb("768M"), 768)
        with self.assertRaises(ValueError):
            parse_memory_mb("1G; touch /tmp/no")
        self.assertEqual(validate_port("25565"), 25565)
        with self.assertRaises(ValueError):
            validate_port(70000)

    def test_native_memory_overrides_docker_heap(self):
        result = validate_server_settings({"MINECRAFT_VERSION": "26.3", "MEMORY": "4G", "TERMUX_MEMORY": "1G"})
        self.assertEqual(result["MEMORY"], "1G")
        args = build_java_args("/usr/bin/java", "/srv/data/paper.jar", "1G")
        self.assertEqual(args, ["/usr/bin/java", "-Xms512M", "-Xmx1G", "-jar", "/srv/data/paper.jar", "--nogui"])

    def test_survivalsmp_defaults_and_safe_world_settings(self):
        result = validate_server_settings({"MINECRAFT_VERSION": "26.3"})
        self.assertEqual(result["WORLD_NAME"], "SurvivalSMP")
        self.assertEqual(result["SEED"], "399918057248930")
        self.assertEqual(result["SERVER_ADDRESS"], "survivalsmp.vy")
        with self.assertRaises(ValueError):
            validate_server_settings({"WORLD_NAME": "../other"})
        with self.assertRaises(ValueError):
            validate_server_settings({"SEED": str(2**63)})
        with self.assertRaises(ValueError):
            validate_server_settings({"SERVER_ADDRESS": "bad host"})

    def test_paper_properties_get_requested_world_and_seed(self):
        import manager

        with tempfile.TemporaryDirectory() as tmp, patch.object(manager, "DATA", Path(tmp)):
            _properties_file({"WORLD_NAME": "SurvivalSMP", "SEED": "399918057248930"})
            content = (Path(tmp) / "server.properties").read_text()
            self.assertIn("level-name=SurvivalSMP", content)
            self.assertIn("level-seed=399918057248930", content)

    def test_env_parser_does_not_execute_values_and_updates_preserve_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("RCON_PASSWORD=secret\nMOTD=$(echo bad)\nJAVA_PORT=25565\n")
            self.assertEqual(parse_env_file(path)["MOTD"], "$(echo bad)")
            update_env_file(path, {"JAVA_PORT": "25566", "EULA": "TRUE"})
            content = path.read_text()
            self.assertIn("RCON_PASSWORD=secret", content)
            self.assertIn("MOTD=$(echo bad)", content)
            self.assertIn("JAVA_PORT=25566", content)
            self.assertIn("EULA=TRUE", content)

    def test_geyser_port_update_preserves_other_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text("bedrock:\n  address: 0.0.0.0\n  port: 19132 # listen\nremote:\n  address: auto\n")
            self.assertTrue(_set_geyser_port(path, 19140))
            self.assertEqual(path.read_text(), "bedrock:\n  address: 0.0.0.0\n  port: 19140 # listen\nremote:\n  address: auto\n")
            self.assertFalse(_set_geyser_port(path, 19140))


class FakeProcess:
    def __init__(self, waits):
        self.stdin = io.StringIO()
        self.waits = list(waits)
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        outcome = self.waits.pop(0) if self.waits else "exit"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("java", timeout)
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class ShutdownTests(unittest.TestCase):
    def test_sends_stop_and_waits_before_signaling(self):
        process = FakeProcess(["exit"])
        message = stop_process(process)
        self.assertIn("stop\n", process.stdin.getvalue())
        self.assertEqual(message, "Server stopped gracefully.")
        self.assertFalse(process.terminated)

    def test_sigterm_is_only_a_timeout_fallback(self):
        process = FakeProcess(["timeout", "exit"])
        message = stop_process(process, graceful_timeout=1)
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertIn("SIGTERM", message)


class DockerPreservationTests(unittest.TestCase):
    def test_existing_docker_deployment_remains_available(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        launcher = (ROOT / "run.sh").read_text()
        dockerfile = (ROOT / "panel" / "Dockerfile").read_text()
        panel = (ROOT / "panel" / "app.py").read_text()
        self.assertIn("itzg/minecraft-server", compose)
        self.assertIn('LEVEL: "${WORLD_NAME:-SurvivalSMP}"', compose)
        self.assertIn('SEED: "${SEED:-399918057248930}"', compose)
        self.assertIn("./data:/data", compose)
        self.assertIn(":19132/udp", compose)
        self.assertIn("docker compose --project-name mcstack up --build", launcher)
        self.assertIn("/var/run/docker.sock", compose)
        self.assertIn("docker-cli-compose", dockerfile)
        self.assertIn('docker("compose"', panel)
        self.assertTrue((ROOT / "termux-run.sh").exists())
        native_launcher = (ROOT / "termux-run.sh").read_text().lower()
        self.assertIn("bash ./install-termux.sh", native_launcher)
        self.assertNotIn("docker compose", native_launcher)
        self.assertNotIn("command -v docker", native_launcher)


if __name__ == "__main__":
    unittest.main(verbosity=2)
