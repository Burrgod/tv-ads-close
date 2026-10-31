---
name: tv-ads-close
description: Safely disable system-level ads on a Xiaomi/Redmi TV over ADB, using a plan artifact, allowlisted packages/settings, device fingerprint, backup and best-effort rollback. Use only when the user owns the TV (or the owner is present and consents), explicitly asks for this, and has enabled ADB. Never root, uninstall, flash, or disable core packages. Present evidence limits before writing.
---

# tv-ads-close

A safety-first agent skill for **system-level** ads on Xiaomi/Redmi TVs.

This is **not** a consumer app, **not** a general ADB toolbox, and **not** an all-ad blocker. If the user wants something outside this scope, stop and say so.

> **First, `cd` to the skill root — the directory containing this `SKILL.md`.** Every command below is relative to that directory. If your working directory is different, prefix commands with `cd <skill-root> &&`.

> Current profile status is **observed (E1)**: commands were run once on one TV, but there was no single-variable A/B test and no second device. It is **not** "verified". Say this out loud before planning.

## When to use

Use only when **all** of these are true:

- The user says the TV is **their own**, or the owner is present and explicitly agrees.
- The user explicitly asks to remove **system** ads (startup / push / shop / short-video / telemetry).
- The TV is a Xiaomi/Redmi Android TV with ADB debugging available.
- The computer and TV are on the same local network.
- A matching profile exists in `profiles/`.

## When not to use

Do not use if:

- The TV is rented, in a hotel/public place, or owned by someone who is not present.
- The user asks for remote operation on someone else's TV.
- The user only wants in-app ads (iQiyi/Tencent/Youku). Out of scope.
- No exact profile match exists for model + codename + brand + Android + SDK + firmware.
- The user asks for root, firmware changes, APK cracking, VPN/DRM bypass, or piracy.

## Hard rules

**MUST**

1. Confirm ownership in plain language and require `--attest-owner`.
2. Tell the user the profile is **observed (E1)**, not verified, and what that means.
3. Suggest the official path for startup ads first: Xiaomi support **950816**, with Ethernet + WiFi MACs.
4. Run `doctor` and `probe` before `plan`. (`doctor` needs `adb`; `demo` does not.)
5. Show the full plan to the user: actions, evidence level, risk, what is not covered, rollback, and the 8-hex confirm code.
6. Require an explicit user confirmation **after** they saw the plan; then run `apply` with `--plan` and `--confirm <code>`.
7. Let the CLI create the backup; keep the printed `restore` command visible.
8. Run `verify`; then ask the user to reboot and observe. Never declare success from a single `getprop`.
9. Remind the user to close ADB debugging afterwards.

**MUST NOT**

1. Never type raw `adb shell` write commands (`settings put/delete`, `pm disable-user/enable`, `pm uninstall`, `pm clear`). All writes go through the CLI.
2. Never run `root`, `su`, `pm uninstall`, `pm clear`, `fastboot`, or flashing commands.
3. Never add packages or settings keys that are not in the CLI allowlist; never edit a profile to bypass it.
4. Never use `--include-observed` unless the user explicitly accepts E1 risk.
5. Never use `--include-risky` without telling the user which medium-risk actions they are accepting.
6. Never use this on a TV the user does not own / is not present for.
7. Never install APKs, "ad-free" builds, proxies, or piracy tools.
8. Never use `--no-auto-restore` on a normal run; never use `--force-device-mismatch` without a second explicit user confirmation.
9. Never upload logs, screenshots, IPs, MACs, serials, or account data.
10. Never treat the confirm code as identity verification — it is a speed bump; the human confirmation is the real gate.

## Workflow

### 0. Scope and official path

```bash
cd <skill-root>   # the directory containing this SKILL.md
```

Say briefly:

- "这个工具只停用小米/红米电视的系统广告组件；首页推荐流和 App 内广告去不掉。"
- "当前只有单机观察配置（E1），不是全面验证。"
- For startup ads: "可以先试官方客服 950816，提供以太网 + WiFi 的 MAC，由厂家关闭；这是目前最低风险的路径。"

If the user still wants to proceed, continue.

### 1. Preflight

```bash
python3 scripts/tv_ads_close.py doctor
python3 scripts/tv_ads_close.py probe --host <TV_IP>
```

Expected: model / firmware / serial tail printed. If `unauthorized` or no device: ask the user to reboot the TV, re-open ADB, keep the screen on, then retry **once**. Stop if it still fails.

### 2. Plan (read-only)

Ask the user to accept E1 explicitly. Then:

```bash
python3 scripts/tv_ads_close.py plan \
  --host <TV_IP> \
  --include-observed \
  --attest-owner \
  --save ./plan.json
```

Only add `--include-risky` if the user explicitly accepts medium-risk actions (push service / cloud config). Read the plan output, including warnings and `未覆盖`.

The plan is valid for **15 minutes**; if it expires, run `plan` again. On an `observed` profile, `plan` without `--include-observed` exits with code 2 and creates no plan — that is intentional.

### 3. Confirm and apply

Show the user:

- device model / firmware / serial tail
- every action with evidence (`E1`) and risk
- not covered: home feed, in-app ads, member ads
- rollback command
- the 8-hex confirm code

Ask: "确认执行吗？执行前会自动备份；失败会尝试自动回滚，若回滚失败会打印手动命令。"

Only after a clear yes:

```bash
python3 scripts/tv_ads_close.py apply \
  --plan ./plan.json \
  --confirm <code> \
  --attest-owner
```

### 4. If anything fails

- Do **not** reboot.
- The CLI will **attempt** to auto-restore; if it prints a manual command (because rollback also failed), run that `restore` command.
- Ask the user for the error text and stop.

### 5. Verify

```bash
python3 scripts/tv_ads_close.py verify --plan ./plan.json
```

Then ask the user to reboot the TV and watch the boot screen.

- No startup ad observed → report success **with caveat** (single observation).
- Ad still there → stop; collect model/firmware/logcat; do not disable random packages.

### 6. Close ADB

Tell the user: 设置 → 账号与安全 → ADB 调试 → 关闭。5555 is a plaintext debugging port.

## Stop conditions

Stop immediately if:

- The user hesitates about ownership, or the TV is not theirs.
- `probe` shows an unknown model/firmware or a device mismatch.
- The plan contains anything outside the allowlist.
- `apply` reports any failure.
- The TV shows a black screen, boot loop, or unresponsive UI.
- The user asks for root, firmware, APK cracking, VPN, or piracy.

## Output format

After a successful run, report:

```text
设备：<brand> <model> / Android <version> / <firmware>
Profile：<id>（status: observed，E1）
计划：<plan_id>（确认码 <code>）
已执行：<settings/包列表，含状态>
备份：<path>
回滚：<restore command>
未覆盖：首页推荐流、App 内广告、会员广告
验证：已运行 verify；请重启电视观察开机过程。
提醒：完成后关闭 ADB 调试。
```

## Privacy

- Do not upload logs, screenshots, IPs, MACs, serials, or account IDs.
- `report` already masks IP and serial tail; still ask the user to review before posting.
- Do not run untrusted forks. If a release exists, verify its tag and SHA256 before use.
- This project is not affiliated with Xiaomi/Redmi.
