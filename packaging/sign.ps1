<#
.SYNOPSIS
    Authenticode-sign the built Apex DNS Changer executables.

.DESCRIPTION
    Signs every *.exe under -Path and then reports the resulting
    Get-AuthenticodeSignature status for each file, so the operator sees the
    outcome instead of having to trust the exit code.

    The script is designed to be called unconditionally from
    packaging/build.ps1, so it tells two very different situations apart:

      * No thumbprint configured. The binaries stay unsigned. A clear,
        actionable warning is printed and the exit code is 0, so an ordinary
        local build still succeeds. Pass -RequireSignature to turn this into
        a hard failure, which is what CI should do.

      * Thumbprint configured but unusable. The exit code is 1. A configured
        yet broken certificate is a real error, not a missing optional step.

    signtool.exe is preferred when it can be located (on PATH or under a
    Windows Kits install) because it gives better diagnostics and lets the
    Authenticode and RFC 3161 digest algorithms be pinned. When the Windows
    SDK is absent the script falls back to Set-AuthenticodeSignature, which
    ships with Windows PowerShell and needs no SDK at all.

    The script targets Windows PowerShell 5.1; pwsh works as well.

.ENVIRONMENT
    APEX_CERT_THUMBPRINT   Fallback thumbprint when -Thumbprint is omitted.

.PARAMETER Path
    Directory searched for *.exe files. Defaults to the repository's dist
    folder, which is what packaging/build.ps1 writes to.

.PARAMETER Thumbprint
    SHA-1 thumbprint of the code signing certificate. The certificate must
    exist in Cert:\CurrentUser\My or Cert:\LocalMachine\My and its private
    key must be accessible. Falls back to $env:APEX_CERT_THUMBPRINT.

.PARAMETER TimestampUrl
    RFC 3161 timestamp service. Timestamping keeps the signature verifiable
    after the signing certificate expires.
    Default: http://timestamp.digicert.com

.PARAMETER RequireSignature
    Exit non-zero when the executables are not signed. Use this in CI.

.EXAMPLE
    pwsh -File packaging/sign.ps1
    Description: Signs dist\*.exe with $env:APEX_CERT_THUMBPRINT when it is
    set, and prints an explanatory warning when it is not.

.EXAMPLE
    pwsh -File packaging/sign.ps1 -Thumbprint 0123456789ABCDEF... -RequireSignature
    Description: Signs with an explicit certificate and fails the run if any
    part of the signature is wrong.

.EXAMPLE
    pwsh -File packaging/sign.ps1 -Path dist -TimestampUrl http://timestamp.digicert.com
    Description: Signs an explicit directory against an explicit timestamp
    service.
#>
[CmdletBinding()]
param(
    [string]$Path,
    [string]$Thumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$RequireSignature
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Path) {
    $Path = Join-Path $ProjectRoot "dist"
}

function Write-Step {
    param([string]$Label)
    Write-Host "==> $Label" -ForegroundColor Cyan
}

function Resolve-SigningCertificate {
    param([Parameter(Mandatory = $true)][string]$CertThumbprint)

    foreach ($store in @("Cert:\CurrentUser\My", "Cert:\LocalMachine\My")) {
        try {
            $found = Get-ChildItem -LiteralPath $store -ErrorAction Stop |
                Where-Object { $_.Thumbprint -eq $CertThumbprint } |
                Select-Object -First 1
        } catch {
            Write-Host "    Skipping $store : $($_.Exception.Message)" -ForegroundColor DarkGray
            continue
        }
        if ($found) {
            return [pscustomobject]@{ Certificate = $found; Store = $store }
        }
    }
    return $null
}

function Find-SignTool {
    $command = Get-Command "signtool.exe" -CommandType Application -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $roots = @()
    foreach ($variable in @("ProgramFiles(x86)", "ProgramFiles")) {
        $base = [Environment]::GetEnvironmentVariable($variable)
        if ($base) {
            $roots += (Join-Path $base "Windows Kits\10\bin")
        }
    }

    foreach ($root in @($roots | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        $found = Get-ChildItem -LiteralPath $root -Filter "signtool.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\" } |
            Sort-Object -Property FullName -Descending |
            Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }
    return $null
}

function Invoke-SignTool {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)]$Certificate,
        [Parameter(Mandatory = $true)][string]$Store,
        [Parameter(Mandatory = $true)][string]$Timestamp,
        [Parameter(Mandatory = $true)][string]$SignTool
    )

    $signArgs = @("sign", "/sha1", $Certificate.Thumbprint, "/s", "My", "/fd", "SHA256", "/td", "SHA256", "/tr", $Timestamp, "/v")
    if ($Store -like "Cert:\LocalMachine\*") {
        $signArgs += "/sm"
    }
    $signArgs += $File

    & $SignTool @signArgs
    if ($LASTEXITCODE -ne 0) {
        throw "signtool sign failed with exit code $LASTEXITCODE"
    }
}

function Invoke-SetAuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)]$Certificate,
        [Parameter(Mandatory = $true)][string]$Timestamp
    )

    # -HashAlgorithm pins the Authenticode digest. Windows PowerShell 5.1 picks
    # the timestamp digest itself, so the RFC 3161 digest cannot be pinned the
    # way signtool /td does; signtool is preferred for that reason.
    $setArgs = @{
        FilePath        = $File
        Certificate     = $Certificate
        HashAlgorithm   = "SHA256"
        TimestampServer = $Timestamp
        ErrorAction     = "Stop"
    }
    $result = Set-AuthenticodeSignature @setArgs
    if ($null -eq $result) {
        throw "Set-AuthenticodeSignature produced no signature object"
    }
}

$Configured = $Thumbprint
if (-not $Configured) {
    $Configured = $env:APEX_CERT_THUMBPRINT
}
$Configured = "$Configured".Replace(" ", "").ToUpperInvariant()

if (-not $Configured) {
    Write-Step "No signing certificate configured"
    Write-Host "    The executables in $Path are left UNSIGNED." -ForegroundColor Yellow
    Write-Host "    Unsigned binaries make Windows SmartScreen show" -ForegroundColor Yellow
    Write-Host "    'Windows protected your PC' on first run, which is the" -ForegroundColor Yellow
    Write-Host "    single biggest barrier to distributing them." -ForegroundColor Yellow
    Write-Host "    To sign, pass -Thumbprint or set the environment variable:" -ForegroundColor Yellow
    Write-Host "        `$env:APEX_CERT_THUMBPRINT = '<sha1 thumbprint>'" -ForegroundColor Yellow
    Write-Host "    The certificate must live in Cert:\CurrentUser\My (or" -ForegroundColor Yellow
    Write-Host "    Cert:\LocalMachine\My) with its private key available." -ForegroundColor Yellow
    Write-Host "    -RequireSignature turns this warning into a hard failure." -ForegroundColor Yellow
    if ($RequireSignature) {
        Write-Host "    -RequireSignature was set, so this is a failure." -ForegroundColor Red
        exit 1
    }
    exit 0
}

Write-Step "Checking $Path for executables"
if (-not (Test-Path -LiteralPath $Path)) {
    Write-Host "    Directory not found: $Path" -ForegroundColor Red
    exit 1
}

$Targets = @(Get-ChildItem -LiteralPath $Path -Filter "*.exe" -File -Recurse | Sort-Object -Property FullName)
if ($Targets.Count -eq 0) {
    Write-Host "    No .exe file found under $Path" -ForegroundColor Red
    exit 1
}
Write-Host "    $($Targets.Count) executable(s) to sign" -ForegroundColor DarkGray

Write-Step "Resolving certificate $Configured"
$Resolved = Resolve-SigningCertificate -CertThumbprint $Configured
if ($null -eq $Resolved) {
    Write-Host "    Certificate $Configured was not found." -ForegroundColor Red
    Write-Host "    Looked in Cert:\CurrentUser\My and Cert:\LocalMachine\My." -ForegroundColor Red
    exit 1
}

$Certificate = $Resolved.Certificate
$Store = $Resolved.Store
Write-Host "    Subject : $($Certificate.Subject)" -ForegroundColor DarkGray
Write-Host "    Store   : $Store" -ForegroundColor DarkGray
Write-Host "    Expires : $($Certificate.NotAfter)" -ForegroundColor DarkGray

if (-not $Certificate.HasPrivateKey) {
    Write-Host "    The certificate has no accessible private key, so it cannot sign." -ForegroundColor Red
    exit 1
}
if ($Certificate.NotAfter -lt (Get-Date)) {
    Write-Host "    WARNING: the certificate is already expired." -ForegroundColor Red
} elseif ($Certificate.NotAfter -lt (Get-Date).AddDays(14)) {
    Write-Host "    WARNING: the certificate expires in less than 14 days." -ForegroundColor Yellow
}

$SignTool = Find-SignTool
if ($SignTool) {
    Write-Step "Signing with signtool ($SignTool)"
    $Method = "signtool"
} else {
    Write-Step "signtool not found, using Set-AuthenticodeSignature"
    $Method = "Set-AuthenticodeSignature"
}

$Failed = @()
foreach ($item in $Targets) {
    try {
        if ($SignTool) {
            Invoke-SignTool -File $item.FullName -Certificate $Certificate -Store $Store -Timestamp $TimestampUrl -SignTool $SignTool
        } else {
            Invoke-SetAuthenticodeSignature -File $item.FullName -Certificate $Certificate -Timestamp $TimestampUrl
        }
        Write-Host "    signed $($item.Name)" -ForegroundColor Green
    } catch {
        Write-Host "    FAILED $($item.Name) : $($_.Exception.Message)" -ForegroundColor Red
        $Failed += $item.Name
    }
}

Write-Step "Verifying signatures"
$Results = @()
$Signed = $true
foreach ($item in $Targets) {
    $Signature = Get-AuthenticodeSignature -FilePath $item.FullName

    $SignerSubject = ""
    $SignerThumbprint = ""
    if ($Signature.SignerCertificate) {
        $SignerSubject = $Signature.SignerCertificate.Subject
        $SignerThumbprint = $Signature.SignerCertificate.Thumbprint
    }
    $TimestampSubject = ""
    if ($Signature.TimeStamperCertificate) {
        $TimestampSubject = $Signature.TimeStamperCertificate.Subject
    }

    # The signer thumbprint is the authoritative check. Status is reported but
    # not relied upon: on a machine without network access or without the
    # issuing root in its store, WinVerifyTrust can report UnknownError or
    # NotTrusted for a perfectly good signature.
    $Matches = ($SignerThumbprint -eq $Certificate.Thumbprint)
    if (-not $Matches) {
        $Signed = $false
    }

    $Results += [pscustomobject]@{
        Name        = $item.Name
        Status      = [string]$Signature.Status
        Signer      = $SignerSubject
        TimeStamper = $TimestampSubject
    }
    if ([string]$Signature.Status -ne "Valid") {
        Write-Host "    NOTE $($item.Name) : $($Signature.Status) - $($Signature.StatusMessage)" -ForegroundColor Yellow
    }
}
$Results | Format-Table -AutoSize

Write-Host ""
if ($Failed.Count -eq 0 -and $Signed) {
    Write-Host "Signing complete via $Method. $TimestampUrl" -ForegroundColor Green
    exit 0
}

if ($Failed.Count -gt 0) {
    Write-Host "Could not sign: $($Failed -join ', ')" -ForegroundColor Red
}
Write-Host "At least one executable is not signed with $Configured." -ForegroundColor Red
exit 1
