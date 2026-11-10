# Minecraft Server Kit

A self-hosted Java Minecraft server with two separate ways to run it:

- **Docker mode** for Linux computers with Docker Engine and Docker Compose v2 (and Docker Desktop on Windows/macOS).
- **Native Termux mode** for non-root Android ARM64 devices. This mode starts Paper directly in Termux and does not use Docker, Compose, containerd, or systemd.

Both modes use the same `data/` world directory. **Never run the Docker and native servers at the same time against that data.** Always stop one deployment before starting the other.

## Docker mode — Linux and desktop computers

Install and start Docker Engine plus the Docker Compose v2 plugin on Linux, or Docker Desktop on Windows/macOS. Then, from the repository directory:

```sh
./run.sh
```

On first launch, the script asks you to accept the [Minecraft EULA](https://aka.ms/MinecraftEULA). The launcher builds the local admin panel and starts the server in the foreground. Open **http://localhost:8080** to see logs, run console/admin commands, change settings, and upload plugin/mod JARs. Press **Ctrl+C** in the terminal to stop the stack. Docker mode retains Paper, Fabric, Forge, NeoForge, Vanilla, and the existing Compose-managed setup.

The panel is bound to localhost and has Docker-socket access; do not port-forward its port. The default Java game port is **25565/TCP** and the Bedrock Geyser port is **19132/UDP**. To accept connections from outside your home network, configure the host firewall and router. Set a whitelist for a private server.

The requested defaults are world folder **`SurvivalSMP`**, seed **`399918057248930`**, and displayed hostname **`survivalsmp.vy`**. The image uses `LEVEL` for the world folder and `SEED` for generation ([image variable docs](https://docker-minecraft-server.readthedocs.io/en/latest/variables/)). The hostname is only a display/config value; it does not create DNS or change the server's bind address. IANA's current delegated-TLD list does not include `.vy`, so ordinary public DNS cannot resolve `survivalsmp.vy` at present ([IANA TLD list](https://data.iana.org/TLD/tlds-alpha-by-domain.txt)). Use a registered domain and point its DNS to the host, then configure router/firewall forwarding. Keep `server-ip` blank so the server listens on its normal interfaces. The seed only determines newly generated terrain. Changing the world name selects a different save folder and leaves other world folders intact; back up worlds before changing either value. Minecraft's [official server guide](https://help.minecraft.net/hc/en-us/articles/360058525452-How-to-Setup-a-Minecraft-Java-Edition-Server) describes the seed and network setup.

This is intended for Linux systems that support the Docker Engine and Compose v2 and the image's CPU architecture. It is not a promise that every Linux distribution, kernel, or device works without installing those prerequisites. On desktop Linux, Docker mode is the supported project workflow; the native launcher below is intentionally Termux-specific.

## Native Android Termux mode

Native mode currently supports **Android ARM64 (aarch64), Termux, and Paper only**. It does not use or alter the Docker Compose implementation. Java mods, Fabric/Forge/NeoForge, and Vanilla remain Docker-mode options. Bedrock joining is provided only when the compatible Geyser/Floodgate Paper plugins load successfully.

### Install and start

1. Install a current Termux app from [F-Droid](https://f-droid.org/packages/com.termux/) or the [official Termux GitHub releases](https://github.com/termux/termux-app/releases). Keep the app and any Termux add-ons from the same source/signing key. Very old or unsupported Play Store builds can have package problems.
2. Open Termux and clone the repo into Termux's **private home directory**, not shared Android storage:

   ```sh
   cd ~
   git clone https://github.com/itsdazzyprince3-sudo/minecraft-server-kit.git
   cd minecraft-server-kit
   bash termux-run.sh
   ```

   The launcher automatically invokes the safe installer if Python or OpenJDK 25 is missing. The installer checks ARM64 and free storage, installs only missing packages, creates directories without replacing existing files, and leaves any existing `.env`, worlds, and native settings untouched. It stops if less than 1.5 GB is free; 5 GB or more is recommended because worlds and backups grow. You can also run `bash install-termux.sh` separately as a preflight.
3. Read and accept the Minecraft EULA when prompted by that first run:

   The same `bash termux-run.sh` command is still running; type `yes` at the EULA prompt if you accept it.

   It starts Paper and a local control page at **http://127.0.0.1:8080**. Logs appear in Termux and are saved to `logs/native-server.log`. The page has status, start/stop/restart, console commands, recent logs, basic settings, Java/architecture information, and process memory reporting. Press **Ctrl+C** in Termux to send Paper its `stop` command, wait for a graceful save, and then stop the manager. SIGTERM/SIGKILL are last-resort fallbacks only.

The panel listens on the phone itself, not the LAN. It does not enable RCON. The startup log and status page show loopback addresses for the phone and the detected local IPv4 address for same-Wi-Fi players, with Java/Bedrock ports. The requested `survivalsmp.vy` name is not publicly resolvable; use a real registered domain/public IP for internet players and configure router/firewall forwarding. Mobile carrier NAT may prevent inbound connections. For plugins, copy a trusted compatible `.jar` into `data/plugins/` and restart the server. The same preset plugin download URLs from `.env` are used when possible; failed optional plugin downloads are logged and do not delete worlds or stop a server download. Native mode does not install arbitrary modpacks or provide a public management panel.

To install dependencies manually instead of using the script, run `pkg update && pkg install python openjdk-25` in Termux, then run `bash termux-run.sh`. OpenJDK 25 is the current package targeted for recent Paper versions.

### Version and Java compatibility

Paper's published recommended Java matrix is: Minecraft **26.1 and later: Java 25**; **1.20 through 1.21.11: Java 21**; **1.17 through 1.19: Java 17**; **1.16.5: Java 16**; **1.12 through 1.16.4: Java 11**; and **1.7.10 through 1.11: Java 8**. The native launcher checks the selected release against the installed Java major before starting. See [PaperMC's current requirements](https://docs.papermc.io/paper/getting-started/).

Native mode defaults to Paper's **STABLE** build channel. `LATEST` resolves through the official PaperMC downloads API. A Minecraft release may exist but have no stable Paper build yet. In that case, the launcher stops with a message rather than silently installing an alpha build. If you explicitly accept the risk, change `paper_channel` to `ALPHA` in `native/config.json`; experimental builds can be unstable and unsupported. PaperMC asks automated download clients to identify themselves with a User-Agent and recommends stable builds; the native downloader follows that guidance. See [PaperMC's downloads-service docs](https://docs.papermc.io/misc/downloads-service/).

For a version change, stop the server and make a complete backup of `data/` first. Change `MINECRAFT_VERSION` in `.env`, then run:

```sh
bash termux-run.sh --update
```

The launcher requires you to type `I HAVE A WORLD BACKUP` before it replaces the Paper JAR. It preserves the previous JAR in `data/server-jar-backups/`; that JAR backup is not a substitute for backing up worlds. A version upgrade can change world data and may not be reversible.

### Termux and Android limitations

Termux runs inside Android's app sandbox. Install and run this project under `$HOME` (normally `/data/data/com.termux/files/home`); shared/emulated storage can lack the file-permission behavior a server needs. The installer requires at least 1.5 GB free and recommends 5 GB or more. The native heap defaults to **1 GB** in `native/config.json`; lower or raise it to fit your phone, but leave memory for Android and Termux itself.

For better odds of remaining active, keep Termux open, plug the device into power, run `termux-wake-lock`, and exempt Termux from battery optimization if Android offers that setting. **This does not guarantee 24/7 uptime.** Android Doze can restrict CPU and network activity, and Android/manufacturer power policies can suspend or kill background processes. Thermals, battery drain, mobile-network restrictions, carrier-grade NAT, and changing IP addresses can also prevent reliable hosting. Do not use this as a production or guaranteed always-on host.

## Shared server configuration and files

The Docker mode and Termux mode can reuse the compatible settings in `.env`: Minecraft version, world name, seed, advertised hostname, Java port, player count, view/simulation distance, difficulty, PvP, whitelist, MOTD, and plugin URLs. Native-only heap/channel/panel settings live in the ignored `native/config.json`. The EULA is requested interactively and recorded in `.env` and `data/eula.txt`.

Worlds and Paper server files are in `data/`. The committed anti-x-ray defaults are in `config/paper-world-defaults.yml`; Termux uses that directory for Paper config when it can safely create the link. If a non-empty `data/config/` already exists, the native runtime leaves it alone rather than replacing it. Back up `data/` and `config/` before changing server software or versions. Never delete either directory as a troubleshooting step unless you intend to remove its contents.

Paper's built-in anti-x-ray is enabled with engine mode 1 in the starter config. AxGraves is preconfigured in the plugin download list for a death-grave workflow; plugin support depends on the selected Paper version. It stores drops at death rather than using keep-inventory. Geyser/Floodgate and ViaVersion/ViaBackwards are likewise version-dependent. Modded Java clients generally cannot be made compatible with Bedrock just by adding Geyser.

## Testing

Run the standard-library tests on Linux/macOS (Python 3 required):

```sh
python3 -m unittest discover -s tests -v
```

They cover Termux/ARM64 detection, Java version parsing and Paper compatibility, configuration validation/loading, generated JVM arguments, graceful shutdown, and checks that the Docker Compose files/workflow remain present. The tests do not download or run a Paper server; the actual Termux environment, plugin downloads, Android networking, and device-specific background behavior must be tested on the Android device.

## Troubleshooting

- **`Run this inside the official Termux app`:** use the Termux app, not a normal Linux shell or an Android shell without Termux's package environment.
- **ARM64 required:** use Docker mode on a desktop/VM or add a separate compatible runtime for another architecture; this native build deliberately refuses unsupported architectures.
- **Java is missing or too old:** run `bash install-termux.sh`; check `java -version`. Paper 26.1+ requires Java 25.
- **No stable build:** keep the stable channel, choose an older supported Paper release, or explicitly opt into `ALPHA` knowing it is experimental.
- **Outside players cannot connect:** verify the server is running, the host firewall/router forwards Java TCP 25565 and (for Bedrock) UDP 19132, and the network permits inbound connections. Mobile carriers commonly restrict inbound hosting.
- **Android stopped the server:** reopen Termux, inspect `logs/native-server.log`, check battery optimization settings, and use a computer or hosted server if continuous uptime matters.
- **Plugins fail:** verify the plugin's Paper/Minecraft version support and dependencies. Read the native log or Docker dashboard logs. Do not download untrusted JARs.

## Main files

- `run.sh` and `docker-compose.yml` — existing Docker foreground workflow.
- `panel/` — Docker dashboard; it depends on Docker CLI and the Docker socket and is not the native Termux panel.
- `install-termux.sh` and `termux-run.sh` — additive Termux installer and foreground launcher.
- `native/manager.py`, `native/runtime.py`, `native/index.html` — native Paper manager, tested helpers, and local control page.
- `tests/test_termux_runtime.py` — native runtime and Docker-preservation tests.
