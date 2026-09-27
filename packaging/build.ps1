<#
.SYNOPSIS
    Build the Apex DNS Changer executables with PyInstaller.

.DESCRIPTION
    Creates an isolated build virtual environment (the project has no runtime
    dependency on PyInstaller) and produces two binaries:

      ApexDNSChanger.exe      windowed, UAC-elevated
      ApexDNSDiagnostics.exe  console, no elevation

    The binaries are then handed to packaging/sign.ps1. Signing is a no-op
    when no certificate is configured, so local builds stay usable; pass
    -SkipSigning to bypass the step entirely.

.EXAMPLE
    pwsh -File packaging/build.ps1
    pwsh -File packaging/build.ps1 -Clean
    pwsh -File packaging/build.ps1 -SkipSigning
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SkipSigning,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $ProjectRoot ".venv-build"
$SignScript = Join-Path $ProjectRoot "packaging\sign.ps1"

function Invoke-Step {
    param([string]$Label, [scriptblock]$Action)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if ($Clean -and (Test-Path -LiteralPath $Venv)) {
    Write-Host "==> Removing $Venv" -ForegroundColor Yellow
    Remove-Item -LiteralPath $Venv -Recurse -Force
}

if (-not (Test-Path -LiteralPath $Venv)) {
    Invoke-Step "Creating build venv" { & $Python -m venv $Venv }
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $VenvPython = Join-Path $Venv "bin/python"
}

Invoke-Step "Installing build dependencies" { & $VenvPython -m pip install --upgrade pip }
Invoke-Step "Installing runtime dependencies" { & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt") }
Invoke-Step "Installing PyInstaller" { & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-build.txt") }
Invoke-Step "Running PyInstaller" { & $VenvPython -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot "packaging\apex_dns.spec") }

$Dist = Join-Path $ProjectRoot "dist"

if ($SkipSigning) {
    Write-Host "==> Skipping signing" -ForegroundColor Yellow
} else {
    Invoke-Step "Signing executables" { & $SignScript -Path $Dist }
}

Write-Host ""
Write-Host "Build complete. Output in $Dist" -ForegroundColor Green
Get-ChildItem -LiteralPath $Dist -Filter "*.exe" -ErrorAction SilentlyContinue |
    Select-Object Name, @{Name = "SizeMB"; Expression = { [math]::Round($_.Length / 1MB, 1) } } |
    Format-Table -AutoSize
