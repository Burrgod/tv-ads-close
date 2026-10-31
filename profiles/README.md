# profiles

机型配置库。**没有匹配的 profile 就不要执行**——CLI 会停止。

## 状态

| status | 含义 | 默认可执行 |
|--------|------|------------|
| `draft` | 结构齐全，但没有可用证据 | ❌ |
| `observed` | 单机执行过、有观察，但未做单变量 A/B | ⚠️ 需 `--include-observed` |
| `verified` | 单变量 + 重启 A/B（E2；E3 为加分） | ✅ |

**当前只有一个 `observed` profile**：`profiles/xiaomi/mitv-mfzp0.json`。这是诚实的现状，不是「已验证」。

## 证据分级

每个 setting / package 都必须有 `evidence`：

| 等级 | 含义 |
|------|------|
| `E0` | 未证实/传闻（draft 才能用） |
| `E1` | 单机观察到效果，但未隔离变量 |
| `E2` | 单变量 + 重启验证（A/B） |
| `E3` | 多机型/多固件复现 |

`verified` 的每个动作必须是 E2/E3，并带 method/before/after/date。

## 允许的包与设置

profile **不能新增**包或设置键。只能引用 CLI 内置的 `ALLOWED_PACKAGES` / `ALLOWED_SETTINGS`：

- 8 个广告/统计包（其中推送、云控为 medium + opt-in）：
  - `com.miui.analytics`、`com.miui.tv.analytics`、`com.xiaomi.statistic`、`com.xiaomi.tvqs`
  - `com.xiaomi.mitv.tvpush.tvpushservice`（medium，opt-in）
  - `com.mitv.shoplugin`、`com.mitv.cloudcontrol`（medium，opt-in）、`com.duokan.videodaily`
- 设置键：
  - `global/mitv.settings.advertise.state`（profile 当前使用）
  - `system/boot_ad_switch`（外部单机型证据，未在本机验证）

新增需要同时改 `scripts/tv_ads_close.py` 和 `tests/`，并说明风险。核心包（桌面、设置、信号源、输入法、账号等）永远拒绝。

## 新增机型

1. 复制 `_template.json` 到 `profiles/<brand>/<model>.json`。
2. 先填 `draft`；用 `probe` 拿到 model/device/brand/android/sdk/firmware 的**精确值**。
3. 一次只改一个动作做验证（改 → 重启 → 观察 → 还原），记录到 `evidence`。
4. 满足 E2 后才改成 `verified`；否则保持 `observed` 或 `draft`。
5. 运行测试与 `doctor`，提 PR。

不要提交：`*` 固件、`verified` 自声明、核心包、任意 settings。
