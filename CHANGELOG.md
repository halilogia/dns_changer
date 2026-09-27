# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - 2026-09-27

Completes the v2.1 roadmap. Not yet pushed to a release.

### Added

**Localization**
- `i18n` package with Turkish and English catalogs covering the UI, the
  diagnostics report and the CLI. 150 keys, with a test asserting both
  catalogs expose the same keys and the same `{placeholder}` set.
- Locale resolves from `--locale`, then the saved setting, then the
  environment (`APEX_DNS_LOCALE`, `LANG`, ...), then
  `GetUserDefaultUILanguage` on Windows.
- Localized provider names, descriptions, badges and card placeholders. Text
  is stored as catalog keys and resolved on access, so switching language takes
  effect immediately rather than only at import time.
- An AST-based test rejects hardcoded Turkish literals in the UI, diagnostics
  and CLI modules, so translations cannot silently regress.

**Settings**
- `core/settings.py` persists the last selected adapter and provider, custom
  DNS addresses, window geometry, language and update preference as JSON in the
  per-user application data directory.
- Writes are atomic (temp file plus `os.replace`) and a corrupt or unreadable
  file falls back to defaults instead of blocking startup.
- The update preference is seeded from the value the installer writes to
  `HKCU\Software\Apex DNS Changer`, so an opt-out during setup is honoured.
  Once the user has saved settings, their stored value wins.

**Auto-update**
- `core/updater.py` queries the GitHub releases API and compares versions.
  Network, HTTP and JSON failures return a structured error instead of raising.
- A startup prompt offers the download page when a newer release exists. Only
  runs for frozen builds, and `--no-update-check` disables it permanently.
- `--check-update` performs the same check from the command line.
- The check sends a `User-Agent`; the default urllib agent is refused by the
  GitHub API.

**Failure reporting**
- `ui/details.py` adds a connection detail window listing every adapter with
  its status, configured DNS servers, DHCP flag, addresses and any backend
  error, plus a summary count of how many connections are up.
- A new `DETAILS` button in the status bar opens it. Failures no longer reduce
  to "some servers did not respond".

**Packaging**
- `packaging/sign.ps1` signs the built executables with Authenticode, using
  `signtool.exe` when present and `Set-AuthenticodeSignature` otherwise. The
  thumbprint comes from `-Thumbprint` or `APEX_CERT_THUMBPRINT`. With no
  certificate it explains the SmartScreen consequence and exits 0, so
  unsigned local builds still work; `-RequireSignature` turns that into a
  failure for CI.
- `packaging/apex_dns.iss` is an Inno Setup 6 installer with a Start menu
  group, an optional desktop shortcut and a post-install launch.
- `build.ps1` gained `-SkipSigning` and invokes the signing step.

### Changed

- `DnsProvider` stores `name_key` / `desc_key` / `badge_key` instead of
  literal text, with `label` / `desc` / `badge` properties resolving them.
- `Ipv6Status.detail` became a `detail_key` plus a resolving property, so the
  IPv6 summary is localized.
- The status bar has a fifth button, so the four action buttons are now laid
  out across five equal columns.
- `--help` and the subcommand descriptions are localized; the locale is now
  resolved before the argument parser is built.

### Fixed

- `ApexDNSDiagnostics.exe` with no arguments started the GUI, because both
  executables are built from the same entry point and `main` defaulted to
  `gui`. The default command is now chosen from the executable name.
- The diagnostics report embedded a `Path` object for the settings location,
  which made `diagnostics-json` fail to serialize. It is now a string.
- Tk `Frame` constructor padding was passed as a 2- or 4-tuple, which Tcl
  rejects; asymmetric padding belongs on the geometry manager.

## [2.0.0] - 2026-09-27

Total rewrite. The 718-line `dns_changer.py` monolith became a layered package
(`core` / `ui` / `diagnostics`), a Windows `.exe` build pipeline was added, and
the app is no longer Windows-only.

### Added

**Command line interface**
- `main.py` entry point with subcommands: `gui`, `diagnostics`,
  `diagnostics-json`, `ping`, `speed`, `doh`, `adapters`, `providers`.
- GUI no longer forces elevation for non-interactive commands, so
  `diagnostics` runs without a UAC prompt.
- `diagnostics-json` emits a machine-readable report for automation.
- `--no-elevation` skips the UAC relaunch (useful for testing).

**DoH and IPv6**
- DNS-over-HTTPS timing across Cloudflare, Google, Quad9, AdGuard and OpenDNS.
- RFC 8484 support: POST with a GET fallback for endpoints that reject POST.
- HTTP/2 transport via `httpx` for endpoints that require it. Quad9 answers
  HTTP/1.1 with `505 HTTP Version Not Supported` per RFC 8484 section 5.2.
- Corrected the Cloudflare endpoint to `/dns-query`; the previous
  `/doh-query` path returns HTTP 404.
- `certifi`'s CA bundle is layered onto the default TLS context. The Windows
  certificate store is missing the SSL.com intermediate that Cloudflare's DoH
  certificate chains through, which caused certificate verification failures.
- IPv6 health check: stack support, global address presence (detected without
  sending packets), AAAA resolution and ICMPv6 round-trip time.
- Turkish and English ping output parsing for RTT and packet loss.

**Windows executables**
- `packaging/build.ps1` creates an isolated build venv and runs PyInstaller.
- `ApexDNSChanger.exe` — windowed GUI, embedded `requireAdministrator` manifest
  so the OS elevates the process before any code runs.
- `ApexDNSDiagnostics.exe` — console build, `asInvoker`, so the diagnostics
  report never triggers an elevation prompt.
- `packaging/apex_dns.manifest` with DPI awareness, Common Controls v6 and
  supported-OS declarations.
- `packaging/icon.ico` generated procedurally by `tools/make_icon.py` (7 sizes,
  standard library only) instead of committing an opaque binary.
- `tools/check_manifest.py` verifies the UAC execution level of a built binary
  by reading it out of the PE resource section.

**Platform support**
- `core/system.py` isolates platform detection; `CREATE_NO_WINDOW` is only
  passed on Windows, which previously raised `AttributeError` elsewhere.
- `NetworkManagerDnsBackend` adds full DNS read/write on Linux via `nmcli`.
- `ReadOnlyDnsBackend` reports resolver state on macOS/BSD and explicitly
  refuses to mutate it instead of failing mid-operation.

**Quality**
- 204 tests: unit, cross-platform guards, DNS wire format, DoH, UI controller
  and CLI subprocess coverage.
- GitHub Actions CI: ruff lint and format, tests on Ubuntu/Windows/macOS across
  Python 3.10 and 3.13, plus a Windows build job that asserts the UAC level and
  smoke-tests the frozen executable.
- `pyproject.toml` with ruff configuration and package metadata.
- `tools/inspect_ui.py` prints a live widget-tree dump for UI verification.

### Changed

- `dns_changer.py` is now a 12-line shim that forwards to `main.main()`, so the
  existing Desktop shortcut, `.bat` launcher and `dns_changer.py` invocation
  keep working.
- `POPULAR_DNS` and the diagnostics provider list were duplicated and had
  drifted apart. Both now read from a single `core/providers.py` catalog, and
  providers are frozen dataclasses instead of mutable dicts.
- The duplicate `measure_dns_latency` implementation was consolidated; the copy
  in the monolith leaked its socket on the timeout path.
- The provider list is no longer mutated as a side effect of typing in the
  custom DNS fields.
- Windows backend reads adapters and DNS state through the NetTCPIP PowerShell
  module with JSON output instead of parsing localized `netsh` text, with
  `netsh` retained as a fallback.
- PowerShell is invoked through `-EncodedCommand` (UTF-16LE base64), avoiding
  quoting, escaping and code-page problems with non-ASCII adapter names on
  Turkish Windows installs.
- `create_shortcut.ps1` prefers the built executable, and the mojibake in its
  output strings was fixed.
- Console output is reconfigured to UTF-8; Turkish text previously printed as
  `zel DNS` on the default Windows code page.
- The speed test no longer blocks the UI. All core calls run on a worker pool.

### Fixed

- `python dns_changer.py --ping HOST` raised `NameError`: the branch called an
  undefined `test_latency_and_loss`.
- Worker threads handed results to Tk via `after()`, which is not safe off the
  main thread and silently never fired. The adapter list never populated and
  the busy flag latched on permanently, leaving the UI permanently disabled.
  Results now travel through a queue drained on the Tk thread.
- `is_valid_ip` used `socket.inet_aton`, which accepts malformed forms such as
  `1.2.3` and `0x7f.1` that Windows later rejects. It now uses `ipaddress`,
  which also enables IPv6 DNS servers.
- Adapter names were interpolated directly into PowerShell command strings.
  They are now quoted as single-quoted literals with `''` escaping.
- The UAC relaunch joined `sys.argv` with spaces, breaking on any path
  containing a space. It now uses `subprocess.list2cmdline`.
- DNS servers with subnet masks in `netsh` output were parsed as addresses.
- IPv4 and IPv6 servers were applied through a single call; they now go to their
  respective address families separately.
- `dnspython` was listed in `requirements.txt` but never used.
- A DNS probe socket leaked on the timeout path in the monolith.

### Removed

- `network_diagnostics.py`, superseded by the `diagnostics` package.
