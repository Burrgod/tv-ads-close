# Troubleshooting

## `unauthorized`

电视没有授权这台电脑。

1. 看电视屏幕，弹出「允许 USB 调试吗？」→ 勾「一律允许」→ 确定。
2. 没弹窗：重启电视 → 重新打开 ADB 调试 → 保持亮屏 → 再连。
3. 仍失败：停止，不要 root，不要用来路不明的工具。

## setup 找不到电视（mDNS）

- 确认电视和电脑同一局域网、ADB 已打开；
- `adb mdns services` 是否能看到 `_adb._tcp`；
- 直接指定：`setup --host <电视IP>`；
- 不要用网段扫描；本项目不提供 scan。

## 电视不弹授权框

部分 HyperOS 机型（实测 MiTV-MFZP0）首次连接不弹框，重启电视后才弹。

1. 重启电视（不是关屏）；
2. 重新打开 ADB 调试；
3. 保持亮屏、停在主页；
4. 再 `probe`。

## 重启后 ADB 连不上

部分机型每次重启都会复位 ADB 开关：设置 → 账号与安全 → ADB 调试 → 重新打开。

## 没有匹配的 profile（退出码 4/5）

不要猜。记录型号/固件，按 [CONTRIBUTING.md](../CONTRIBUTING.md) 提交机型报告。当前只有一台机型的 profile。

## 计划被拒绝 / 没有动作（退出码 2 或 9）

- 退出码 2：常见于 observed profile 没加 `--include-observed`（不会生成计划），或参数/确认码错误。
- 退出码 9：计划过期、被改动、profile 改动、型号变化。重新 `plan`。

## 计划被拒绝（退出码 9）

- 计划过期：重新 `plan`；
- 计划被手改：重新 `plan`；
- profile 被修改：重新 `plan`；
- 换了一台电视：重新 `plan`。

## 执行失败 / 回滚

- 不要重启电视；
- 看 CLI 输出的备份路径与 `restore` 命令；
- 运行 `restore --host <IP> --backup <path> --attest-owner`；
- 仍异常：重启电视 → 重开 ADB → 再 restore；最后才考虑恢复出厂（会丢数据）。

## 黑屏 / 桌面异常

1. 等 10 秒，按 Home；
2. 对电视说「打开设置」，重新打开 ADB；
3. 如果 ADB 还能连：`restore`；
4. 重启电视；
5. 最后才恢复出厂。

## 系统更新后广告回来

OTA 可能重新启用组件。重新 `probe` + `plan`；固件变了就先确认 profile 是否仍匹配，不要复用旧结论。

## 还原失败（退出码 6/7）

- 7：备份不属于当前电视；确认 IP/序列号，或 `--force-device-mismatch --i-accept-device-mismatch`（高风险，需两个开关）；
- 6：逐项失败；看输出，重试；用 `restore` 重试，不要用 `pm uninstall`；
- 外部备份：需 `--allow-external-backup`。

## 锁文件

`~/.tv-ads-close/locks/` 下有锁文件说明另一个进程正在操作。确认没有进程后删除；2 小时以上的锁会被视为过期。

## Windows

未验证。CLI 用 Python 标准库，但 `adb` 路径、引号、Python 启动命令未测试。建议先在 macOS/Linux 上使用。

## 仍然不行

不要 root、不要刷机、不要安装「去广告版」APK。记录型号/固件/命令/错误，开 issue。
