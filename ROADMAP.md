# Roadmap

Planning document for Apex DNS Changer. This file contains **open work only** —
completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and removed from here
as it ships.

Items are ordered by impact-per-effort.

## v2.1 — Ship quality and everyday usability

- [ ] **Code-sign the executables.** Unsigned binaries trigger SmartScreen
      "Windows protected your PC" on first run, which is the single biggest
      barrier to distributing them. Requires an Authenticode certificate.
- [ ] **Installer and Start menu entry.** An Inno Setup or MSIX installer with
      an uninstaller, file associations for the report output and a Start menu
      shortcut that carries the elevation flag.
- [ ] **Auto-update.** Signed releases with a lightweight check; the app is
      currently frozen at whatever version was downloaded.
- [ ] **Persist user settings.** Last selected adapter, provider and window
      geometry are not remembered between runs.
- [ ] **Localization.** Strings are hardcoded Turkish. Extract them so the
      English UI in this changelog is not aspirational.
- [ ] **Failure reporting.** "Some servers did not respond" is the only
      diagnosis a user gets. Surface per-adapter errors in a detail view.

## v2.2 — Networking depth

- [ ] **DNS leak test.** Compare the resolver seen by a probe domain against the
      configured provider, so the user can confirm a VPN or a DoH resolver is
      actually in use.
- [ ] **Local DoH proxy.** The app measures DoH but cannot *enforce* it. Binding
      `127.0.0.1:5353` and forwarding to a DoH endpoint would give real encrypted
      resolution; a stub resolver or a NRPT-style split is needed, and this is
      the only way to make per-domain DoH routing possible at all.
- [ ] **Tracert / MTR.** Latency and packet loss exist, but not the path, so
      "which hop is congested" is unanswerable.
- [ ] **IPv6 DNS configuration.** Reading and reporting work, but `set_dns_servers`
      only reaches IPv6 through a secondary PowerShell call with no UI affordance.
- [ ] **Per-app DNS on Windows.** Needs a WFP or split-tunnel driver; large
      effort, decide whether it is worth it before starting.

## v2.3 — Platform reach

- [ ] **macOS DNS write support.** Currently refused by design, since resolver
      configuration is a system-wide network preference and macOS 13+ replaced
      `networksetup` with `scutil`/`dsconfigutil`. Needs a real decision about
      privileged helper installation.
- [ ] **systemd-resolved backend.** `resolvectl` output is localized, so a
      robust parser is required; as a session-scoped writer it is simpler than
      the NetworkManager backend but loses persistence.
- [ ] **Windows on ARM64.** The spec currently builds x64 only.

## Ideas not yet scheduled

- Scheduled profile switching (for example, gaming DNS during play hours).
- Encrypted DNS as the default rather than an opt-in measurement.
- Per-domain override table.
- Telemetry, opt-in and off by default.
