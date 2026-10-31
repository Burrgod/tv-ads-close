# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/); versioning: SemVer.

## [0.2.0] - 2026-10-31

### Changed — breaking

- `apply` now accepts only a **plan artifact** (`--plan plan.json` + `--confirm <8-hex code>`); it no longer runs a profile directly.
- Removal of `scan` (LAN ADB port scanner) and `--allow-untested`.
- Package and settings **allowlists** are built into the CLI; profiles cannot add arbitrary packages/keys.
- Device identity now includes a domain-separated serial hash, codename, brand, Android, SDK, and exact firmware.
- Backup schema v2: atomic writes, tool/schema version, serial hash, per-key `present/value`; baseline vs latest.
- `restore` verifies device/allowlist/values, writes a pre-restore backup, supports `--dry-run`, and exits non-zero on failure.
- Apply is fail-fast: on failure it stops and auto-restores (unless `--no-auto-restore`).
- Profile schema v2 with `status: draft|observed|verified` and per-action `evidence` objects (E0–E3).
- The MiTV-MFZP0 profile is downgraded to **observed (E1)**: only one machine, one run, no single-variable A/B; `boot_ad_switch_show` and the no-op `boot_ad` were removed from the profile and the allowlist.
- Docs rewritten: status/limits first, per-host install, evidence model, legal/takedown notes.

### Added

- `verify` (read-only) and `doctor` (environment/self-check); `report` (redacted).
- `--include-observed` (E1 actions) and `--include-risky` (medium/opt-in actions) on `plan`.
- Plan integrity hash **and HMAC signature**; expiry; device binding; lock file; journal; re-probe under lock.
- Tests: 53 unit/integration tests with a deterministic fake `adb` (plan/apply/restore/failure/auto-restore/tamper/expiry/device mismatch/allowlist/bypass).

### Removed

- `scan`, `--allow-untested`, `boot_ad_switch_show`, `boot_ad` (no-op) from the profile and allowlist. `system/boot_ad_switch` remains as an externally observed candidate, not default-applied.

## [0.1.0] - 2026-10-29

- Initial review skeleton: CLI demo/probe/plan/apply/restore, one profile, 9 safety tests, docs.
