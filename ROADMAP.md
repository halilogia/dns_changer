# Roadmap

Planning document for Apex DNS Changer. This file contains **open work only** —
completed work is recorded in [CHANGELOG.md](CHANGELOG.md) and removed from here
as it ships.

Items are ordered by impact-per-effort.

## v2.1 — Ship quality and everyday usability

- [x] **Code-sign the executables.** `packaging/sign.ps1` signs with
      Authenticode and `build.ps1` calls it. **The certificate is still
      missing**, so binaries remain unsigned and SmartScreen still warns.
      Supply one via `APEX_CERT_THUMBPRINT` to close this.
- [x] **Installer and Start menu entry.** `packaging/apex_dns.iss`, with
      optional desktop shortcut. Not yet compiled: Inno Setup is not
      installed locally, so it is verified by inspection only.
- [x] **Auto-update.** `core/updater.py` plus a startup prompt and
      `--check-update`. The check reaches the API now that the repository is
      published, but it has no release to find until one is tagged.
- [x] **Persist user settings.** `core/settings.py`, atomic and
      corruption-tolerant.
- [x] **Localization.** Turkish and English across UI, report and CLI.
- [x] **Failure reporting.** `ui/details.py` connection detail window.
- [x] **Continuous integration.** Lint plus tests on Ubuntu, Windows and macOS,
      a Windows build job that asserts the UAC level, and a separate job for
      the tests that need real network access.

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

## Blocked on something outside the code

- **Tag a release.** The repository is public, but with no tagged release the
  updater has nothing to offer and `diagnostics-json` reports the check as
  failed. This also gates verifying the Inno Setup installer end to end.
- **Obtain a code-signing certificate.** The pipeline is done; only the
  certificate is missing.
- **Install Inno Setup.** `apex_dns.iss` has never been compiled, so it is
  verified by inspection only.
