# 兼容性

## 状态定义

| status | 含义 | 执行门槛 |
|--------|------|----------|
| `draft` | 结构齐全、无可用证据 | 不可执行 |
| `observed` | 单机执行过、有观察，未做单变量 A/B | `--include-observed` + 用户明确同意 |
| `verified` | 单变量 + 重启 A/B（E2） | E2/E3 动作默认可执行；medium/opt-in 仍需 `--include-risky` |

**「执行过」不等于「有效」，更不等于「安全」。**

## 当前矩阵

| 品牌 | 型号 | 代号 | 系统 | 固件 | 状态 | 证据 |
|------|------|------|------|------|------|------|
| Xiaomi | MiTV-MFZP0 | walle | Android 9 / HyperOS 2.0.2496.0 | `25.5.22.2496` | ⚠️ observed | 2026-10-27 单机单次；未做单变量 A/B |

> 只有这一行。没有第二台设备，就没有「多机型验证」这回事。

## 如何让一个机型变成 verified

1. 先在 `draft`/`observed` 下跑通只读流程；
2. **一次只改一个动作**（一个 setting 或一个包）：
   - 记录改前状态；
   - 执行；
   - 重启；
   - 记录现象（开机广告 / 副作用）；
   - 还原；
3. 重复到每个动作都有 E2 证据；
4. 填写 `evidence`（method/before/after/date）与 `tested_at`；
5. 提 PR，附日志与复现步骤；维护者复核后改 `verified`。

## 提交机型报告

按 [CONTRIBUTING.md](../CONTRIBUTING.md) 的模板，附：

- model / device / brand / android / sdk / firmware 精确值
- ADB 状态
- 单变量验证步骤与结果
- 副作用检查
- `logcat` 中 `BOOT_ADVERT` 行
- 已删除个人信息

## 已知不支持

- 非小米/红米电视
- 未打开 ADB / 无法授权
- Android 11+ 无线调试随机端口（当前只支持 5555）
- 首页 PatchWall 推荐流、App 内广告、会员广告
- 公共/酒店/租赁设备
