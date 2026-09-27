# Creates a Desktop shortcut for Apex DNS Changer.
#
# Prefers the packaged executable (which carries its own UAC manifest) and falls
# back to running main.py through pythonw when no build is present.
#
#   pwsh -File create_shortcut.ps1

$ErrorActionPreference = "Stop"

$desktop = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$root = $PSScriptRoot
$exe = Join-Path $root "dist\ApexDNSChanger.exe"
$script = Join-Path $root "main.py"

$shortcutPath = Join-Path $desktop "Apex DNS Changer.lnk"
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($shortcutPath)

if (Test-Path -LiteralPath $exe) {
    $Shortcut.TargetPath = $exe
    $Shortcut.Arguments = ""
    Write-Host "Kisayol hedefi: $exe"
} else {
    $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $pythonw) {
        throw "pythonw.exe bulunamadı ve dist\ApexDNSChanger.exe de yok. Önce packaging\build.ps1 çalıştırın."
    }
    $Shortcut.TargetPath = $pythonw
    $Shortcut.Arguments = "`"$script`""
    Write-Host "Shortcut hedefi: $pythonw $script"
}

$Shortcut.WorkingDirectory = $root
$Shortcut.IconLocation = Join-Path $root "packaging\icon.ico"
$Shortcut.Description = "Apex DNS Changer"
$Shortcut.Save()

if (Test-Path -LiteralPath $exe) {
    # The exe already requests elevation, so no shortcut flag is needed.
    Write-Host "Kisayol olusturuldu: $shortcutPath" -ForegroundColor Green
} else {
    # Set the "Run as administrator" bit (byte 21, 0x20) on the .lnk.
    $bytes = [System.IO.File]::ReadAllBytes($shortcutPath)
    $bytes[21] = $bytes[21] -bor 0x20
    [System.IO.File]::WriteAllBytes($shortcutPath, $bytes)
    Write-Host "Kisayol olusturuldu ve yonetici yetkisi eklendi: $shortcutPath" -ForegroundColor Green
}
