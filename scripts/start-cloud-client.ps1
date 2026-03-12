param(
    [string]$ServerBaseUrl = "http://neco-vps:18080",
    [string]$DeviceId = $env:COMPUTERNAME,
    [string]$Label = $env:COMPUTERNAME
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
$tokenFile = Join-Path $PSScriptRoot ".bridge-token.local"
$bridgeScript = Join-Path $repoRoot "scripts\\run_bridge.py"

if (-not (Test-Path $python)) {
    throw "Python venv not found at $python"
}

if (-not (Test-Path $tokenFile)) {
    throw "Bridge token file not found at $tokenFile"
}

$token = (Get-Content $tokenFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "Bridge token file is empty."
}

$existingBridgeProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like "python*" -and
    $_.CommandLine -like "*scripts\\run_bridge.py*" -and
    $_.CommandLine -like "*$repoRoot*"
}

foreach ($process in $existingBridgeProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

$bridgeArgs = @(
    "`"$bridgeScript`"",
    "--server-base-url", "`"$ServerBaseUrl`"",
    "--token", "`"$token`"",
    "--device-id", "`"$DeviceId`"",
    "--label", "`"$Label`""
) -join " "

$normalizedBaseUrl = $ServerBaseUrl.TrimEnd("/")
$launchUrl = "{0}/?session={1}" -f $normalizedBaseUrl, [System.Uri]::EscapeDataString($DeviceId)

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "& `"$python`" $bridgeArgs"
) -WorkingDirectory $repoRoot

Write-Host "Bridge started for device '$DeviceId'."
Write-Host "Session URL: $launchUrl"

try {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $launchUrl
    $startInfo.UseShellExecute = $true
    [System.Diagnostics.Process]::Start($startInfo) | Out-Null
} catch {
    Write-Warning "Browser auto-open failed. Open this URL manually:"
    Write-Host $launchUrl
}
