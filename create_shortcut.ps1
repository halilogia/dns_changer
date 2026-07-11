$desktop = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
Write-Output "Desktop path is: $desktop"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$desktop\Apex DNS Changer.lnk")
$Shortcut.TargetPath = "pythonw.exe"
$Shortcut.Arguments = '"C:\Users\emre_\.gemini\antigravity\scratch\dns_changer\dns_changer.py"'
$Shortcut.WorkingDirectory = "C:\Users\emre_\.gemini\antigravity\scratch\dns_changer"
$Shortcut.IconLocation = "C:\Windows\System32\shell32.dll,18"
$Shortcut.Save()

Write-Output "Shortcut saved to: $desktop\Apex DNS Changer.lnk"
