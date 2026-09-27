; ---------------------------------------------------------------------------
; Apex DNS Changer - Inno Setup 6 installer script
;
; Build order (see packaging/build.ps1):
;     1. packaging\build.ps1              -> dist\ApexDNSChanger.exe
;                                           dist\ApexDNSDiagnostics.exe
;     2. packaging\build.ps1 (sign step)  -> the exes are Authenticode-signed
;     3. ISCC packaging\apex_dns.iss      -> dist\ApexDNSChanger-2.0.0-setup.exe
;     4. re-run packaging\sign.ps1        -> signs the installer itself
;
; Step 4 exists because sign.ps1 walks dist\ recursively, so compiling the
; installer after the build automatically leaves only the new setup.exe to sign.
;
; Every Source path below is relative to this file, so the script must stay in
; packaging\ next to icon.ico.
;
; Compile from the command line with:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\apex_dns.iss
; ---------------------------------------------------------------------------

#define MyAppName "Apex DNS Changer"
#define MyAppVersion "2.0.0"
#define MyAppExeName "ApexDNSChanger.exe"
#define MyDiagnosticsExeName "ApexDNSDiagnostics.exe"
#define MyAppPublisher "Halil Emre Kuyupinar"

[Setup]
; Stable identifier: never change it, or Setup treats the next run as a
; different application and the old one is never uninstalled. The doubled
; brace is the Inno Setup escape for a literal leading brace.
AppId={{52CC8549-16BB-4939-BF00-889BE416230D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no

; Output goes next to the binaries, into the same dist folder.
OutputDir=..\dist
OutputBaseFilename=ApexDNSChanger-{#MyAppVersion}-setup

; icon.ico sits next to this script, so a bare relative name is resolved
; against packaging\.
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} installer

; The GUI writes DNS settings, so installation itself needs elevation and the
; per-machine {autopf} destination needs it as well.
PrivilegesRequired=admin

; x64compatible covers x64 Windows and Arm64 Windows 11 running x64 binaries
; under emulation. This token needs Inno Setup 6.3 or newer; on 6.0 to 6.2 the
; equivalent value is x64, and ArchitecturesAllowed accepts the same tokens.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Writes a detailed install log, which is the first thing to ask for when a
; user reports a broken install.
SetupLogging=yes
; Ask Restart Manager to close a running copy instead of failing the file copy.
CloseApplications=yes

; No LicenseFile directive on purpose: it is a hard compile error when the file
; cannot be found, and the licence is shipped as an ordinary installed file
; below (guarded by skipifsourcedoesntexist) so that the script still compiles
; from an extracted copy of packaging\ that has no repository root above it.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; The application UI is Turkish. Add the following line once a project-local
; Turkish .isl is committed; it is left commented out because the compiler
; fails on any MessagesFile it cannot resolve.
; Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
; Desktop shortcut, off by default.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; Update checking. The checker itself is still an open ROADMAP item, so all
; this task does today is record the preference in HKCU (see [Registry]); the
; application reads nothing yet. Keeping the switch means the installed
; preference is already in place when the updater lands.
Name: "autoupdate"; Description: "Check for application updates when the program starts"; GroupDescription: "Updates:"; Flags: checked

; Post-install launch. Inno's own "Run the program" checkbox is only shown
; when a task named runafterinstall exists, which is what makes the launch
; in [Run] optional and skippable.
Name: "runafterinstall"; Description: "Start {#MyAppName} after the installation finishes"; GroupDescription: "Post-install:"; Flags: checkedonce

[Files]
; Both binaries are built by PyInstaller from main.py; they differ only in
; their subsystem (windowed vs console) and in the UAC level baked into their
; manifests. ignoreversion is correct here because these are the
; application's own private files, not shared ones.
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#MyDiagnosticsExeName}"; DestDir: "{app}"; Flags: ignoreversion

; MIT licence, copied next to the executables. skipifsourcedoesntexist makes
; the compiler skip the entry instead of erroring out when the file is not
; reachable relative to this script.
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Main entry: the Start menu program group.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Change DNS servers and run network diagnostics"

; The diagnostics tool is the same entry point, so the subcommand is passed
; explicitly; without it a bare launch would fall through to the GUI.
Name: "{group}\Network Diagnostics"; Filename: "{app}\{#MyDiagnosticsExeName}"; Parameters: "diagnostics"; WorkingDir: "{app}"; Comment: "Print a network and DNS diagnostics report"

Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

; Desktop entry, created only when the desktopicon task is selected.
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "Change DNS servers and run network diagnostics"

; Elevation of the shortcuts
; -------------------------
; There is deliberately no runasadmin flag here. The [Icons] section supports
; only these flags: closeonexit, createonlyiffileexists, dontcloseonexit,
; excludefromshowinnewinstall, preventpinning, runmaximized, runminimized,
; uninsneveruninstall and useapppaths. An unrecognised flag is a compile
; error, so a guessed runasadmin would break the build instead of elevating
; anything.
;
; The documented way to request elevation is the application manifest, and
; ApexDNSChanger.exe already ships one: packaging\apex_dns.manifest sets
; requestedExecutionLevel to requireAdministrator and packaging\apex_dns.spec
; embeds it via uac_admin=True. Launching the shortcut therefore raises the UAC
; prompt before any application code runs, which is what setting the .lnk
; "Run as administrator" bit would have achieved, and unlike the bit it
; survives being copied or recreated. create_shortcut.ps1 in the repository
; root relies on exactly the same behaviour.
;
; The only other mechanism is the RUNASADMIN application compatibility layer
; under HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\
; Layers. Microsoft advises against installers writing it, and it would be
; redundant here anyway.
;
; Note that ApexDNSDiagnostics.exe intentionally stays asInvoker, so its
; shortcut must not request elevation.

[Registry]
; Persist the update preference chosen by the autoupdate task. One of the two
; entries always applies, so the value is always present and always correct.
; Delete this section once the updater reads the value itself.
Root: HKCU; Subkey: "Software\Apex DNS Changer"; ValueType: dword; ValueName: "CheckForUpdates"; ValueData: 1; Flags: uninsdeletekey; Tasks: autoupdate
Root: HKCU; Subkey: "Software\Apex DNS Changer"; ValueType: dword; ValueName: "CheckForUpdates"; ValueData: 0; Flags: uninsdeletekey; Tasks: not autoupdate

[Run]
; Launch the GUI once the files are in place. runascurrentuser is intentionally
; not set: the entry runs in the installer's context, and the executable's own
; manifest is what decides the final execution level.
; skipifsilent keeps unattended installs from opening a window.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Tasks: runafterinstall

[UninstallDelete]
; Remove anything left behind in the application folder, then the folder
; itself, so an uninstall does not leave {autopf}\Apex DNS Changer behind.
Type: filesandordirs; Name: "{app}"
