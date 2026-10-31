# 发布前检查清单

> 目标：**不带着假证据、假链接、假承诺发布。** 任何一项不满足，就先别发。

## 仓库

- [ ] 仓库 `Burrgod/tv-ads-close` 已创建（或改 URL）；README 安装命令地址正确
- [ ] Description / topics 已填；License 被 GitHub 识别为 MIT
- [ ] 独立 git 仓库：首次 commit、`v0.2.0` tag、Release 附 SHA256
- [ ] CI 全绿（3.9/3.11/3.12 + macOS；单测、demo、profile 校验、链接、MAC 隐私扫描）
- [ ] `git status` 干净；无 `__pycache__`、无本地计划/备份文件

## 内容诚实性

- [ ] README/SKILL 首屏写明：**observed (E1)，单机单次，不是已验证**
- [ ] 没有把「执行过命令」写成「广告已去掉」
- [ ] 「能去掉 / 去不掉」表与 profile/证据一致
- [ ] 没有「一键/全机型/100%」字样
- [ ] 没有暗示厂商关联；没有官方 Logo

## 隐私 / 法务

- [ ] 无真实 IP / MAC / serial / 账号 / 本机路径
- [ ] DISCLAIMER / SECURITY / CONTRIBUTING / LICENSE 齐全
- [ ] 只允许本人/受托在场；禁止公共/租赁/远程代操作
- [ ] 无 APK / 破解 / VPN / DRM / 盗版内容
- [ ] 下架/投诉 SOP 已就位（docs/legal.md）
- [ ] 律师复核（如决定要做）

## 可用性

- [ ] 从零 clone → `demo` → `doctor` 通过（`demo` 不需要 adb）
- [ ] 至少 1 台真机完整走通 probe → plan → apply → verify → restore（录屏/日志留档）
- [ ] 冷读：3 位未参与的人 5 分钟内能说清「能去什么/不能去什么/怎么还原」
- [ ] 安装说明按宿主分列：Claude Code / Codex / DSH / Cursor
- [ ] 第二台设备/固件实测（E3 加分；没有就如实维持 observed，并在 README 说明）

## 发布后

- [ ] 72 小时值守 issue
- [ ] 记录首批用户的机型/结果/支持时长
- [ ] 30 天复盘：真实用户 < 20 → 停止推广投入，降级为个人工具
