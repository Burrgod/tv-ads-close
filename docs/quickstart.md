# Quickstart

## 环境

- macOS（当前唯一实测环境）；Linux/Windows 未验证
- Python 3.9+
- `adb`（Android platform-tools）
- 电脑和电视在同一局域网
- 小米/红米 Android TV，已打开 ADB 调试

## 电视端

1. 设置 → 关于本机 → **产品型号**，连按 5 次，开启开发者模式。
2. 设置 → 账号与安全 → **ADB 调试** → 打开。
3. 记下电视 IP；电视保持亮屏。
4. 若首次连接不弹授权框：重启电视、重开 ADB、保持亮屏后再连。

> 部分 HyperOS 机型没有「开发者选项 / USB 调试」，只有「账号与安全 → ADB 调试」，这是正常的。

## 安装

```bash
git clone https://github.com/Burrgod/tv-ads-close.git tv-ads-close
cd tv-ads-close
python3 scripts/tv_ads_close.py demo      # 不需要 adb，先看计划
python3 scripts/tv_ads_close.py doctor   # 需要 adb；没有 adb 会退出 8
```

## 只读探测

```bash
python3 scripts/tv_ads_close.py probe --host 192.168.1.23
```

确认型号、固件、序列号尾号。没有精确 profile 会直接停止。

## 预演

```bash
python3 scripts/tv_ads_close.py plan \
  --host 192.168.1.23 \
  --include-observed \
  --attest-owner \
  --save ./plan.json
```

- `--include-observed`：当前 profile 是 E1（单机观察），必须显式加。
- 需要停用推送/云控（中风险）再加 `--include-risky`。
- 输出包含动作、证据、风险、未覆盖、回滚方式、8 位确认码。
- 计划 **15 分钟有效**；超时重新 `plan`。
- observed profile 不加 `--include-observed` 时不会生成计划（退出码 2）。

## 执行

确认后：

```bash
python3 scripts/tv_ads_close.py apply \
  --plan ./plan.json \
  --confirm <8 位确认码> \
  --attest-owner
```

执行前自动备份；失败会 best-effort 自动回滚；成功打印 `restore` 命令。

## 验证

```bash
python3 scripts/tv_ads_close.py verify --plan ./plan.json
```

然后重启电视，观察开机过程。**自动检查不能替代人工观察。**

## 还原

```bash
python3 scripts/tv_ads_close.py restore \
  --host 192.168.1.23 \
  --backup ~/.tv-ads-close/backups/<文件>.json \
  --attest-owner
```

## 回到最初状态

第一次 `apply` 会另存一份 `baseline-<序列号哈希>.json`；之后重复 `apply` 不会覆盖它。要回到**第一次 apply 前**的状态：

```bash
python3 scripts/tv_ads_close.py restore \
  --host 192.168.1.23 \
  --backup ~/.tv-ads-close/backups/baseline-<hash>.json \
  --attest-owner
```

> 最新备份是「本次执行前」，不等于「最初状态」；二者不要混用。

## 收尾

设置 → 账号与安全 → **关闭 ADB 调试**。5555 是明文端口。

## 下一步

- 遇到问题：[troubleshooting.md](troubleshooting.md)
- 机型支持：[compatibility.md](compatibility.md)
- 贡献：[../CONTRIBUTING.md](../CONTRIBUTING.md)
