# Contributing

最需要的是**带证据的机型报告**；第二台设备的复现（E3）是加分项，不是 verified 的门槛。代码 PR 也欢迎，但安全优先。

## 机型报告

开 issue（Device report 模板），包含：

- 品牌、型号、代号、Android 版本、SDK、固件号
- ADB 状态：可用 / unauthorized / 不弹窗 / 没有入口
- 在哪个步骤、执行了什么
- **单变量验证**：改一个动作 → 重启 → 观察 → 还原；不是「一起改了，广告没了」
- 副作用：主页、设置、信号源、语音、投屏、蓝牙、输入法、应用商店、OTA
- 关键日志（`logcat` 中 `BOOT_ADVERT` 行）
- 已删除 IP / MAC / 序列号 / 账号 / 截图中的个人信息

## 新增 profile

1. 复制 `profiles/xiaomi/mitv-mfzp0.json` 或 `profiles/_template.json`。
2. 填 `brand/model/device/android/sdk/firmware`（必须精确匹配）。
3. 状态只能先填 `draft`；有 E1 证据可填 `observed`；**E2（单变量 + 重启 A/B）才能填 `verified`**。
4. 每个动作必须有 `evidence` 对象（level / method / before / after / date）。
5. 只能使用 CLI 内置 allowlist 里的包和设置键；新增需要同时改 `scripts/tv_ads_close.py` 和测试，不能只改 JSON。
6. 提交 PR，附证据与复现步骤；`verified` 至少需要维护者复核。

**不接受**：没有证据的 `verified`、`verified: true` 之类的自声明、任意 settings、核心包、`pm uninstall`、root/刷机。

## 代码

- Python 3.9+，仅标准库（除非有强理由）。
- 安全逻辑必须在 CLI 里，不能只写在 SKILL.md。
- `probe`/`plan`/`verify` 必须只读；`apply`/`restore` 必须备份 + 门禁。
- 不允许加入 `pm uninstall`、`pm clear`、`root`、`su`、`fastboot`、刷机。
- 任何安全相关改动都要加测试。
- 运行：

```bash
python3 -m unittest discover -s tests -v
```

## 举报安全问题

见 [SECURITY.md](SECURITY.md)，不要开公开 issue。

## License

提交即同意以 MIT License 授权你的贡献。
