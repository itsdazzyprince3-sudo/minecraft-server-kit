$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
$dockerPath = if ($dockerCommand) { $dockerCommand.Source } else { 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' }
if (-not (Test-Path -LiteralPath $dockerPath)) {
    throw 'Docker Desktop is required on Windows. Install and start Docker Desktop, then run .\start.ps1 again.'
}

function Set-EnvValue([string]$Key, [string]$Value) {
    $envPath = Join-Path $PSScriptRoot '.env'
    $lines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $envPath) {
        [System.IO.File]::ReadAllLines($envPath) | ForEach-Object { $lines.Add($_) }
    }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($Key) + '=')) {
            $lines[$i] = "$Key=$Value"
            $found = $true
        }
    }
    if (-not $found) { $lines.Add("$Key=$Value") }
    [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
}

$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination $envPath
    $bytes = [byte[]]::new(24)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    Set-EnvValue 'RCON_PASSWORD' ([Convert]::ToHexString($bytes).ToLowerInvariant())
    Write-Host 'Created private .env from .env.example.'
}

$passwordLine = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^RCON_PASSWORD=' } | Select-Object -First 1
if ($passwordLine -eq 'RCON_PASSWORD=change-me' -or -not $passwordLine) {
    $bytes = [byte[]]::new(24)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    Set-EnvValue 'RCON_PASSWORD' ([Convert]::ToHexString($bytes).ToLowerInvariant())
}

$eulaLine = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^EULA=' } | Select-Object -First 1
if ($eulaLine -ne 'EULA=TRUE') {
    Write-Host 'Read the Minecraft EULA: https://aka.ms/MinecraftEULA'
    if ((Read-Host 'Do you accept the Minecraft EULA? Type yes to continue') -cne 'yes') {
        throw 'The EULA was not accepted; the server was not started.'
    }
    Set-EnvValue 'EULA' 'TRUE'
}

& $dockerPath compose version *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable. Update Docker Desktop and retry.' }
& $dockerPath info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is installed but its engine is not running. Start Docker Desktop and retry.' }

$env:PROJECT_DIR = '/project'
$env:HOST_PROJECT_DIR = $PSScriptRoot.Replace('\', '/')
Write-Host 'Starting the Minecraft server and local control panel.'
Write-Host 'Join from this PC at localhost:25565. The control panel is http://localhost:8080.'
& $dockerPath compose --project-name mcstack up --build
exit $LASTEXITCODE
