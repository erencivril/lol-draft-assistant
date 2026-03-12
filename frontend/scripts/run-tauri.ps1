param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $TauriArgs
)

$ErrorActionPreference = "Stop"

function Add-PathEntry {
  param([string] $PathEntry)

  if ([string]::IsNullOrWhiteSpace($PathEntry)) {
    return
  }

  if (-not (Test-Path $PathEntry)) {
    return
  }

  $pathEntries = ($env:Path -split ";") | Where-Object { $_ }
  if ($pathEntries -contains $PathEntry) {
    return
  }

  $env:Path = "$PathEntry;$env:Path"
}

function Import-BatchEnvironment {
  param([string] $BatchFile)

  $lines = cmd.exe /c "`"$BatchFile`" >nul && set"
  foreach ($line in $lines) {
    $separatorIndex = $line.IndexOf("=")
    if ($separatorIndex -lt 1) {
      continue
    }

    $name = $line.Substring(0, $separatorIndex)
    $value = $line.Substring($separatorIndex + 1)
    Set-Item -Path "Env:$name" -Value $value
  }
}

function Find-VcVars64 {
  $vswherePath = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
  if (Test-Path $vswherePath) {
    $installationPath = & $vswherePath -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($installationPath) {
      $candidate = Join-Path $installationPath "VC\Auxiliary\Build\vcvars64.bat"
      if (Test-Path $candidate) {
        return $candidate
      }
    }
  }

  $fallbackPaths = @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
  )

  foreach ($candidate in $fallbackPaths) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return $null
}

function Get-CargoTargetDir {
  $root = Join-Path $env:LOCALAPPDATA "ourtbx"
  $targetDir = Join-Path $root "cargo-target"
  New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
  return $targetDir
}

if (-not $TauriArgs -or $TauriArgs.Count -eq 0) {
  $TauriArgs = @("dev")
}

Add-PathEntry (Join-Path $env:USERPROFILE ".cargo\bin")

if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) {
  throw "Cargo bulunamadi. Rustup kuruluysa yeni bir terminal acin veya C:\Users\eren\.cargo\bin yolunu PATH'e ekleyin."
}

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
  $vcvarsPath = Find-VcVars64
  if (-not $vcvarsPath) {
    throw "MSVC build tools bulunamadi. Visual Studio Build Tools yuklu olmali."
  }

  Import-BatchEnvironment $vcvarsPath
}

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
  throw "MSVC derleyicisi yuklenemedi."
}

$frontendRoot = Split-Path -Parent $PSScriptRoot
$env:CARGO_TARGET_DIR = Get-CargoTargetDir
$tauriCliPath = Join-Path $frontendRoot "node_modules\.bin\tauri.cmd"

if (-not (Test-Path $tauriCliPath)) {
  throw "Tauri CLI bulunamadi. once 'npm install' calistirin."
}

Push-Location $frontendRoot
try {
  & $tauriCliPath @TauriArgs
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
