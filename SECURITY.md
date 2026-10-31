# 安全与隐私

## 设计约束

- **本地运行**：CLI 只通过本机 `adb` 与局域网电视通信；无云端、无账号、无遥测。
- **无凭证**：不保存 ADB 私钥、小米账号、设备序列号明文（只存哈希与尾号）。
- **不执行任意命令**：写入动作的包名/设置键/值都经过 allowlist 与正则校验；恢复时按签名备份回写原值；`settings` 值与包名用 `shlex.quote`；只允许固定的 adb shell 命令。
- **计划产物**：`apply` 只接受 `plan` 生成的计划文件；计划有 HMAC 签名、完整性哈希、过期与设备绑定，被改动/过期/设备不符会拒绝。
- **备份与回滚**：写入前备份（原子写、0600）；失败会 best-effort 自动回滚（回滚失败会打印手动 `restore`）；`restore` 校验设备指纹、HMAC 备份签名与 allowlist。
- **签名密钥**：`~/.tv-ads-close/backup.key` 与 `plan.key`（0600，原子创建），只在本机；丢失或换机后旧备份/旧计划不能直接使用。
- **不 root、不卸载、不刷机**：只做 `pm disable-user/enable` 与 `settings put/delete`。

## 报告安全问题

请**不要**开公开 issue。发布后使用 GitHub Security Advisories；当前可在 issue 中 @Burrgod。不要在公开 issue 里贴设备信息。

请包含：

- 受影响版本 / commit
- 复现步骤
- 影响范围
- 建议修复（如有）

## 范围

在范围内：

- 通过 profile / CLI 参数注入命令
- 绕过包或设置 allowlist
- 计划产物校验绕过
- 备份越界写入或错误设备还原
- 本地数据泄露

不在范围内：

- 运行被篡改的 fork
- root / 第三方固件 / 被修改的 adb 导致的问题
- 厂端固件限制

## 信任

只运行本仓库的 release，并核对 tag 与 SHA256。不要运行删除了 allowlist、加入 `pm uninstall` 或索要账号密码的 fork。
