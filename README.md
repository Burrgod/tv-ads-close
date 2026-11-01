# tv-ads-close

> 给 AI Agent 和极客用的**小米/红米电视系统广告停用**工具：先预演、再确认、best-effort 可回滚。
> **Not a cleaner.** 不是清垃圾/清内存/全平台广告拦截器。
> **Not an app.** 是一个 Skill + 确定性 CLI + 机型配置库。

> **当前状态：单机观察版（observed / E1）。**
> 只在一台 **MiTV-MFZP0 / Android 9 / 25.5.22.2496** 上执行过，**没有做单变量对照，也没有验证所有副作用**。
> 当时 `boot_ad` 的原值本来就是 0（写入是 no-op），唯一真正改动的设置项 `mitv.settings.advertise.state` 语义**未单独验证**；8 个包里默认只启用 6 个低风险包，另 2 个中风险包需 `--include-risky`。
> 因此默认 `plan` 会被拒绝（无动作，退出码 2）；需要你明确接受风险后加 `--include-observed`。
> 这不是「一键去所有广告」，也不会替你做决定。

---

## 30 秒判断：适不适合你

| 条件 | 不满足会怎样 |
|------|--------------|
| 电视是你自己的，或所有人在场并同意 | 不要用；项目明确禁止公共/租赁/远程代操作 |
| 小米 / 红米 Android TV，能打开「ADB 调试」 | 用不了；非小米设备没有 profile |
| 电脑和电视在同一个局域网 | 连不上 |
| 你会用终端，电脑有 Python 3.9+ 和 `adb` | 无法运行；目前只实测 macOS |
| 你能接受「开机时看一眼、出问题自己按文档回滚」 | 不要用；没有一键恢复按钮 |

> ⚠️ **最坏情况**：可能出现黑屏、桌面异常或需要恢复出厂。出问题先按 [docs/troubleshooting.md](docs/troubleshooting.md) 回滚，不要重启或乱停包。

## 你只需要做 3 件事

| 你做 | Agent / CLI 做 |
|------|----------------|
| 1. 电视：开「ADB 调试」 | 发现电视（mDNS，不扫网段） |
| 2. 电视弹窗：点「允许 USB 调试」 | 连接、探测、匹配机型、列出计划 |
| 3. 重启电视，看一眼开机过程 | 备份、执行、失败回滚、verify、给回滚命令 |

其余步骤（找 IP、装依赖检查、重试、读日志、生成计划）都收在 `setup` / `plan` / `apply` 里。

**先去试官方通道**：小米电视开机广告可拨 **950816**（以小米官方客服口径为准），提供以太网 MAC + WiFi MAC，由厂家协助关闭。这是目前**最低风险**的路径，不依赖本项目。

> 说明：广电总局《公共场所电视服务提升实施指南》只适用于**公共场所**电视，不是家用电视的授权依据；本项目也不服务公共/租赁设备。

## 能做什么 / 不能做什么

| 目标 | 状态 | 说明 |
|------|------|------|
| 开机广告 | ⚠️ 单机观察（E1） | 2026-10-27 一台机器执行后重启未播放；未做单变量验证 |
| 推送弹窗、商城、短视频、统计组件 | ⚠️ 单机观察（E1） | 命令执行过；未逐包验证效果/副作用 |
| 首页 PatchWall 推荐流 | ❌ 不支持 | 属于桌面内容；本项目不碰桌面 |
| 爱奇艺/腾讯/优酷 App 内广告 | ❌ 不支持 | 属于 App 自身 |
| 会员专属广告 | ❌ 不支持 | 属于平台规则 |
| 所有小米电视 | ❌ 不支持 | 只有 1 台机型 profile；未知机型直接停止 |

> **「E1 / observed」是什么意思**：执行过命令、有过一次观察，但没有隔离变量、没有第二台设备复现。它**不是**「已验证」。
> 证据分级规则见 [docs/design.md](docs/design.md)。

## 它怎么保护你

不是靠「承诺小心」，是靠**代码门禁 + 流程确认 + 审计记录**。注意：确认码与 `--attest-owner` 是减速带，不是身份认证；真正的确认来自人看过计划。

1. **先出计划，才能执行**：`plan` 生成带确认码的计划文件（**15 分钟有效**）；`apply` 只接受这个文件，计划被改过、过期、设备不符都会拒绝。
2. **白名单**：allowlist 共 8 个包、2 个设置键；**默认只启用 6 个低风险包 + 1 个设置键**，推送/云控 2 个中风险包需 `--include-risky`。`adb_enabled`、桌面、设置、输入法、账号等一律拒绝，profile 也加不进去。清单见 [profiles/README.md](profiles/README.md#允许的包与设置)。
3. **设备指纹**：备份绑定电视序列号的哈希；`restore` 发现不是同一台电视默认拒绝（`--force-device-mismatch` 可强制，高风险）。
4. **失败即停 + best-effort 回滚**：任一动作失败会停止，并按备份尝试自动还原；若回滚也失败，会打印手动 `restore` 命令。不会继续扩大改动面。
5. **可证伪验证**：`verify` 检查设置、包状态、核心包和日志；**不把单条 `getprop` 当作成功证据**，最终以重启观察为准。
6. **无遥测**：不联网、不上传设备信息；备份与签名密钥只在本机 `~/.tv-ads-close/`。

## 安装

> 仓库地址为 `Burrgod/tv-ads-close`；若尚未创建，先建同名仓库（见 [docs/release-checklist.md](docs/release-checklist.md)）。

### 人类用户（不装 Skill）

```bash
git clone https://github.com/Burrgod/tv-ads-close.git tv-ads-close
cd tv-ads-close
python3 scripts/tv_ads_close.py demo      # 不接电视，先看样例（不可执行）
python3 scripts/tv_ads_close.py setup     # 发现电视、等授权、检查机型（需要 adb）
# 或：python3 scripts/tv_ads_close.py setup --host 192.168.1.23
```

需要：Python 3.9+、`adb`（macOS：`brew install android-platform-tools`）、电视已开 ADB。

### Claude Code

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/Burrgod/tv-ads-close.git ~/.claude/skills/tv-ads-close
cd ~/.claude/skills/tv-ads-close   # 命令都在 Skill 根目录执行
```

### Codex / DeepSeek Harness

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/Burrgod/tv-ads-close.git ~/.agents/skills/tv-ads-close
cd ~/.agents/skills/tv-ads-close   # 命令都在 Skill 根目录执行
```

### Cursor

Cursor 不读 `SKILL.md`。把 [`.cursor/rules/tv-ads-close.mdc`](.cursor/rules/tv-ads-close.mdc) 复制到你项目的 `.cursor/rules/` 下，或让 Cursor 读本仓库的 `AGENTS.md`。

> 安装后，Skill 目录里包含 `SKILL.md`、`scripts/`、`profiles/`；不要只拷 `SKILL.md`，否则 CLI 和配置都不在。

## 快速开始（真实设备）

### 1. 电视端

- 设置 → 关于本机 → 产品型号，连按 5 次，开启开发者模式。
- 设置 → 账号与安全 → **ADB 调试** → 打开。
- 记下电视 IP；电视保持亮屏。
- 首次连接可能不弹授权框：重启电视、重开 ADB、保持亮屏后再试（详见 [docs/troubleshooting.md](docs/troubleshooting.md)）。

### 2. 只读探测

```bash
python3 scripts/tv_ads_close.py probe --host 192.168.1.23
```

看到型号、固件、序列号尾号、包数量，再继续。

### 3. 预演（不会改任何东西）

```bash
python3 scripts/tv_ads_close.py plan \
  --host 192.168.1.23 \
  --include-observed \
  --attest-owner \
  --save ./plan.json
```

- `--include-observed`：允许执行 E1（单机观察）动作。**这是本项目当前唯一的启用方式。**
- 如果还要停用推送/云控（中风险），再加 `--include-risky`。
- 输出会列出：动作、证据等级、风险、未覆盖范围、回滚方式、**8 位确认码**。

### 4. 执行（写入）

把计划展示给设备所有人，确认后：

```bash
python3 scripts/tv_ads_close.py apply \
  --plan ./plan.json \
  --confirm <plan 输出的 8 位确认码> \
  --attest-owner
```

执行前自动备份；失败会 best-effort 自动回滚；成功会打印完整 `restore` 命令。

### 5. 验证

```bash
python3 scripts/tv_ads_close.py verify --plan ./plan.json
```

然后**重启电视，观察开机过程**。`verify` 的自动检查不能替代人工观察。

### 6. 还原

```bash
python3 scripts/tv_ads_close.py restore \
  --host 192.168.1.23 \
  --backup ~/.tv-ads-close/backups/<备份文件>.json \
  --attest-owner
```

### 7. 收尾

到 设置 → 账号与安全 → **关闭 ADB 调试**。5555 是明文调试端口，不要长期暴露。

> 第一次 `apply` 会另存一份 `baseline-<hash>.json`；之后重复 `apply` 只生成新备份，不会覆盖 baseline。要回到**第一次 apply 前**的状态，用 baseline，不要用最新备份。

## 命令

所有命令都在 clone 后的**仓库根目录**执行。

| 命令 | 写入 | 作用 |
|------|------|------|
| `demo` | 否 | 用假设备展示样例（不连接设备、不写文件、不出确认码） |
| `setup` | 否 | mDNS 发现电视、等待授权、探测机型；不需要手输 IP |
| `doctor` | 否（本地检查，会创建备份目录） | 检查 Python / adb / 备份目录 / profiles / 签名密钥 |
| `probe` | 否 | 只读探测设备 |
| `plan` | 否（只写本地计划文件） | 生成计划文件（`--include-observed` / `--include-risky` / `--attest-owner`） |
| `apply` | 是 | 按计划执行；需要 `--plan`、`--confirm`、`--attest-owner` |
| `verify` | 否 | 只读验证计划是否生效 |
| `restore` | 是 | 按备份还原；默认只接受备份目录文件 |
| `report` | 否 | 输出脱敏设备报告（供 issue） |

**高级选项（不建议日常使用）**：

- `apply --no-auto-restore`：失败时不自动回滚（只在你知道自己在做什么时用；正常流程不要加）。
- `restore --force-device-mismatch --i-accept-device-mismatch`：备份与当前电视不一致时强制还原（高风险，需要两个开关）。
- `restore --allow-external-backup`：允许使用备份目录之外的文件（需自行确认来源）。

退出码：`0` 成功；`2` 用法错误（含 observed profile 无 `--include-observed` 导致无动作）；`3` 未授权/连不上；`4` 无 profile；`5` 固件未验证；`6` 部分失败；`7` 设备不匹配；`8` 环境缺失；`9` 计划被改动/过期/型号变化。

## 已测试设备

| 型号 | 系统 | 固件 | 状态 |
|------|------|------|------|
| Xiaomi MiTV-MFZP0（walle） | Android 9 / HyperOS 2.0.2496.0 | `25.5.22.2496` | ⚠️ observed（E1，单机单次） |

没有你的机型？**不要猜**，按 [CONTRIBUTING.md](CONTRIBUTING.md) 提交机型报告。

## 限制

- 只实测 macOS；Windows/Linux 未验证（CLI 用 Python 标准库，理论可移植，但 `adb`/引号行为未测）。
- 只支持 5555 端口；Android 11+ 无线调试的随机端口/配对未覆盖。
- 只做 `pm disable-user` 和 `settings put/delete`；不 root、不卸载、不刷机。
- 备份与计划都带本机 HMAC 签名，密钥在 `~/.tv-ads-close/backup.key` / `plan.key`（0600）。换电脑或删除 key 后，旧备份/旧计划不能直接使用；必须安全迁移密钥。重新 plan/apply 不会恢复旧状态。
- OTA 可能复活组件；恢复出厂会清掉停用状态。
- 不处理首页推荐流、App 内广告、会员广告。
- 与小米/红米无关联，非官方。

## 法务

- 仅用于**本人拥有的设备**，或**所有人在场并明确同意**的协助；禁止租赁/酒店/公共场所设备、远程代操作。
- 免费、开源、不提供商业支持、不承诺效果。
- 免责声明不能完全免除责任；使用前请读 [DISCLAIMER.md](DISCLAIMER.md) 与 [docs/legal.md](docs/legal.md)。
- 系统更新/保修政策以厂商为准。

## 发布前

如果你要发布这个仓库，先过一遍 [docs/release-checklist.md](docs/release-checklist.md)。

## 贡献

最需要的是**带证据的机型报告**；第二台设备的复现（E3）是加分项。见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

MIT，见 [LICENSE](LICENSE)。
