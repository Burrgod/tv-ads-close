## What changed

## Safety impact

- [ ] Still read-only for probe/plan/verify/report
- [ ] apply/restore still require backup + gates
- [ ] No `pm uninstall` / `pm clear` / root / flash / APK install
- [ ] Allowlist unchanged, or change is justified + tested
- [ ] No `observed` profile marked `verified` without E2 evidence

## Evidence (profiles)

- Model / firmware / codename:
- Single-variable steps + reboot observation:
- Restore verified? yes/no:
- Side effects checked:

## Tests

- [ ] `python3 -m unittest discover -s tests -v`
- [ ] `python3 scripts/tv_ads_close.py demo`
- [ ] CI should pass
