# AGENTS.md

本文件是给**在本仓库里工作的 AI**看的；用户使用说明见 [SKILL.md](SKILL.md) 与 [README.md](README.md)。

## 这是什么

- 一个给 AI Agent 用的 Skill：`SKILL.md` + 确定性 CLI（`scripts/tv_ads_close.py`）+ 机型配置（`profiles/`）。
- 目标：安全地停用小米/红米电视的**系统级**广告组件；不碰桌面、App 内广告、root、刷机。

## 给使用本 Skill 的 Agent

1. 先读 `SKILL.md`，按流程 `setup → plan → 展示计划 → 用户确认 → apply → verify`。
2. **写入只能通过 CLI**；不要手写 `adb shell` 的 `settings put/delete`、`pm disable-user/enable`。
3. 当前 profile 是 `observed (E1)`，不是「已验证」；必须在对话里说明。
4. `apply` 必须带 `--plan`、`--confirm <plan 输出的 8 位码>`、`--attest-owner`。
5. 任何失败都不要重启电视；按 CLI 提示 `restore`。
6. 用户未明确同意 E1/中风险动作时，不要加 `--include-observed` / `--include-risky`。

## 给改代码的 Agent

```bash
python3 -m unittest discover -s tests -v
python3 scripts/tv_ads_close.py demo
```

硬约束（不得为了「更好用」而放松）：

- 包与 settings 必须走 `ALLOWED_PACKAGES` / `ALLOWED_SETTINGS`；新增要同时改测试。
- `probe`/`plan`/`verify`/`report` 只读；`apply`/`restore` 必须备份 + 门禁。
- 不允许 `pm uninstall`、`pm clear`、`root`、`su`、`fastboot`、刷机。
- 不允许把 `observed` profile 写成 `verified`；`verified` 必须有 E2 证据（单变量 + 重启 A/B）。
- 不允许加回 `scan`、`--allow-untested` 这类绕过门禁的入口。
- 任何安全相关改动都要加测试；发布前跑完整测试与隐私扫描。

## 文件地图

- `SKILL.md` — Agent 使用说明书
- `scripts/tv_ads_close.py` — CLI（唯一写入路径）
- `profiles/` — 机型配置（schema v2，带 evidence）
- `tests/` — 单测 + fake adb 集成测试
- `scripts/try-in-sandbox.sh` — 无电视体验脚本（假设备）
- `docs/` — quickstart / troubleshooting / compatibility / legal / design
- `README.md` — 人看的首页（状态、限制、安装）
