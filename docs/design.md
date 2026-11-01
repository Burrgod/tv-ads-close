# 设计说明

> 一句话：**把「ADB 去广告」从一个容易翻车的命令清单，做成一个有边界、可预演、best-effort 可回滚、AI 能安全执行的流程。**

## 为什么不是 App

| 形态 | 问题 |
|------|------|
| 手机 App | iOS 无法执行 ADB；Android 要处理配对/商店/兼容；审核风险 |
| 小程序 | 不能执行 ADB，只能做引导 |
| 桌面 GUI | 可用，但签名/公证/杀软/更新成本高 |
| **Skill + CLI + profiles** | 目标用户是已经在用 AI 助手的人；脚本可审计、可组合；发布成本最低 |

## 威胁模型

| 威胁 | 设计回答 |
|------|----------|
| Agent 跳过预演直接写 | `plan` 生成计划文件；`apply` 只接受计划，校验哈希/设备/过期 |
| Agent 自己扩展命令 | 写入只能走 CLI；包/键 allowlist；未知一律拒绝 |
| 停错核心包（现实案例：同类项目 #884 变砖） | 代码级黑名单 + allowlist；profile 无法新增 |
| 还原到另一台电视 | 序列号哈希绑定；restore 不匹配拒绝 |
| 执行到一半失败/断电 | journal + fail-fast + best-effort 自动回滚；restore 幂等 |
| 误报成功 | 所有 adb 调用检查返回码；`pm list packages` 失败视为硬错误；verify 三件套 |
| 权限升级/隐私 | 不 root/卸载/刷机；无遥测；备份本机 0600；报告脱敏 |
| 用户误以为「全都能去」 | README/SKILL 首屏钉死「只系统广告」；plan 固定输出未覆盖范围 |

## 核心机制

### 1. 计划产物（plan artifact）

- `plan` 输出动作、证据、风险、确认码（8 位）和计划文件；
- 计划包含：profile SHA256、动作哈希、设备指纹、创建/过期时间、完整性哈希；
- `apply` 只接受计划文件；被改过、过期、换设备 → 拒绝（退出码 9/7）。

**它是减速带，不是身份认证**：确认码可以被复制；真正的门是「人看过计划」。文档必须诚实说明。

### 2. 白名单

- `ALLOWED_PACKAGES`：8 个广告/统计包；推送/云控为 medium + opt-in；
- `ALLOWED_SETTINGS`：2 个已知键（profile 当前只用 1 个）；
- profile 只能引用表内项；新增要改代码 + 测试；
- 核心包（桌面/设置/信号源/电视管家/语音/投屏/输入法/账号/商店/OTA/SystemUI/PackageInstaller）永远拒绝。

### 2.5 发现与 setup

- `setup` 用 mDNS（`adb mdns services`）找电视，不扫网段；失败时让用户给 IP；
- 轮询等待电视授权，不要求用户手动 `adb connect`；
- 连上后只读探测、匹配 profile，并打印下一步 `plan` 命令；
- 仍然不做任何写入。

### 3. 设备身份

- `ro.serialno` 哈希（不存明文）+ 尾号展示；
- 匹配 model + device + brand + android + sdk + firmware；
- 备份绑定序列号哈希；restore 前比对。

### 4. 备份 / journal / fail-fast

- 写入前原子备份（0600），首次另存 baseline；
- 逐动作 journal；失败停止并自动 restore；
- `restore` 有 pre-restore 备份、dry-run、读回验证、失败非 0；
- 默认只接受备份目录内文件，外部文件需显式开关。

### 5. 证据分级

| 等级 | 含义 | 默认执行 |
|------|------|----------|
| E0 | 未证实 | 否 |
| E1 | 单机观察，未隔离变量 | 需 `--include-observed` |
| E2 | 单变量 + 重启 A/B | 是（verified 的最低门槛） |
| E3 | 多机型复现 | 是 |

当前 profile 全部是 E1，所以默认 `plan` 会被拒绝（无动作，退出码 2）——这不是 bug，是诚实的现状。

### 6. 可证伪验证

`verify` 检查设置值、包状态、核心包、`logcat` 中的 `BOOT_ADVERT` 行；最终以**用户重启观察**为准。单条 `getprop` 不作为成功证据。

## 非目标

- 手机 App / 小程序 / GUI
- 多品牌首发（先小米/红米）
- 去 App 内广告 / 首页推荐流 / 会员广告
- root / 卸载 / 刷机 / 破解 APK / VPN / DRM
- 公共/租赁/酒店设备
- 自动更新 / 云端兼容库 / 遥测

## 「verified」需要什么

1. 一个动作单独执行；
2. 记录改前值/现象；
3. 重启；
4. 对比改前/改后（A/B）；
5. 还原并确认恢复；
6. 重复到每个动作；
7. （加强项，不是 verified 门槛）第二台设备或第二固件复现（E3）；
8. PR 附证据，维护者复核。

没有这个过程，就只有 `observed`。

## 仓库结构

```text
SKILL.md              Agent 说明书
scripts/tv_ads_close.py  CLI（唯一写入路径）
profiles/             机型配置（schema v2 + evidence）
tests/                单测 + fake adb 集成测试
docs/                 quickstart / troubleshooting / compatibility / legal / design
README.md             人看的首页
```
