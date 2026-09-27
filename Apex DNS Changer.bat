@echo off
rem Launches Apex DNS Changer elevated via the UAC manifest of the packaged exe,
rem or through PowerShell when running from source.
setlocal
cd /d "%~dp0"

if exist "%~dp0dist\ApexDNSChanger.exe" (
    start "" "%~dp0dist\ApexDNSChanger.exe"
    exit /b 0
)

powershell -NoProfile -Command "Start-Process pythonw -ArgumentList 'main.py' -WorkingDirectory '%~dp0' -Verb RunAs"
