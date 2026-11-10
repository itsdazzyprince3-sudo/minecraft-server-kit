# Minecraft Server Kit

A self-hosted Java server with a local web dashboard for logs, server-console commands, settings, and uploading plugins or mods. Docker Compose runs the server and panel on your own machine.

## Start it

1. Install and start Docker Desktop (Windows/macOS) or Docker Engine with Docker Compose v2 (Linux).
2. Read the [Minecraft EULA](https://aka.ms/MinecraftEULA). On the first launch, the script asks you to confirm that you accept it.
3. Run:

   ```sh
   git clone https://github.com/itsdazzyprince3-sudo/minecraft-server-kit.git
   cd minecraft-server-kit
   chmod +x run.sh
   ./run.sh
   ```

   The repository URL will be updated when the repo is published. On macOS/Linux, `bash run.sh` also works if the executable bit was lost.

The launcher builds the dashboard and starts both containers in the foreground. Open **http://localhost:8080**. Logs stream in the terminal and are also shown in the page. Press **Ctrl+C** in that terminal to stop the stack. Re-running the command starts it again. The first startup downloads the server and may take a few minutes.

This is not hosted by GitHub and does not run while your machine is off, asleep, or Docker is stopped. Your friends can connect only while the server is running. For internet access, allow the Java port over TCP and Bedrock port over UDP in your computer firewall/router. The dashboard is deliberately bound to `127.0.0.1`; do not port-forward its panel port.

## Included setup

- Paper is the default Java server software, with auto-downloads configured for Geyser/Floodgate (Bedrock joining) and ViaVersion/ViaBackwards (older Java client compatibility, subject to plugin and Minecraft version support).
- The default game ports are Java **25565/TCP** and Bedrock **19132/UDP**.
- The dashboard displays container status and recent logs, supports start/stop/restart, and sends server-console commands over authenticated RCON. Examples include `op`, `ban`, `tp`, `kill`, `whitelist add`, and `save-all`.
- The dashboard can edit core server settings and apply them by recreating the server container. It accepts `.jar` uploads into `data/plugins` for Paper or `data/mods` for Fabric/Forge/NeoForge.
- The default memory limit is 4 GB with conservative view/simulation distances. Tune these in the dashboard or `.env` to fit your computer. More players, loaded chunks, and heavy mods require more resources.
- Paper's built-in anti-x-ray is enabled by the tracked starter config in `config/paper-world-defaults.yml` using engine mode 1 as a lighter default. Tune it there and restart if desired. Use a compatible anti-cheat plugin if desired; no anti-cheat plugin is preinstalled.

## Versions, mods, and cross-play

The default `MINECRAFT_VERSION=LATEST` follows the server image's latest supported release. You can select a specific upstream-supported release in the dashboard, including `26.3` only if it has been released and the server image supports it. Arbitrary or future version numbers cannot be guaranteed. Version changes may require a new server download and could affect the world; make a backup first.

Paper is intended for plugins. Fabric, Forge, and NeoForge are separate server types intended for mods. The server dashboard routes uploaded JAR files according to the selected type, but it does not resolve mod dependencies or install a client modpack. Players need compatible mod versions, and most Java mods do not work for Bedrock clients. Geyser offers Bedrock access to compatible Java servers; it does not make arbitrary Java modpacks playable on Bedrock.

For a death chest, anti-cheat, or other plugin, upload a trusted plugin JAR in the dashboard while using Paper, then restart the server. Check that the plugin explicitly supports your Paper/Minecraft version. Death-chest plugins store death drops in a chest/grave; this is not keep-inventory. Do not download JARs from untrusted sites.

## Admin and security

Use the dashboard to run console commands directly. Enable the whitelist in settings for a private server, then add players with `whitelist add PlayerName`. The RCON password is randomly generated in `.env`; that file is ignored by Git and should stay private. The dashboard has access to the local Docker socket because it needs to manage the server, so keep it bound to localhost and never expose it to the public internet.

## Data and backups

Worlds, plugin/mod files, and server configuration live in `data/`. Stop the stack and copy the whole `data/` directory somewhere safe before changing server software or Minecraft version. Do not delete `data/` unless you intend to erase your worlds and configuration. `.env` contains local settings and the RCON secret; it is not committed.

## Troubleshooting

- **Docker not found / not running:** install Docker Desktop or Docker Engine + Compose v2, start Docker, then retry.
- **A port is already in use:** change `JAVA_PORT`, `BEDROCK_PORT`, or `PANEL_PORT` in `.env` and rerun. Java uses TCP; Bedrock uses UDP.
- **Outside players cannot join:** check the host firewall and router port forwarding; ensure the server is running and use the correct public address/port. Some ISPs use carrier-grade NAT and do not allow inbound port forwarding.
- **Version fails to download:** set `MINECRAFT_VERSION=LATEST` or choose a version supported by the upstream server image.
- **Plugin/mod does not load:** confirm the server type, Minecraft version, and plugin/mod dependencies. Read the server logs in the dashboard.

## Main files

- `run.sh` — one-command foreground launcher.
- `docker-compose.yml` — server and local panel services.
- `panel/` — local control page and API.
- `.env.example` — editable defaults; the launcher creates a private `.env` on first run.
