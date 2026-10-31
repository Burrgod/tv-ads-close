#!/usr/bin/env python3
"""tv-ads-close: safety-first system-ad control for Xiaomi/Redmi TVs over ADB.

Safety contract:
- Read-only by default; `probe`/`plan`/`verify`/`report` never write.
- Writes happen only through `apply`/`restore`, only from a saved plan or backup.
- Packages and settings keys are allowlisted in this file; profiles cannot add new ones.
- Every write creates a backup; failures stop the run and restore automatically.
- Never root, uninstall, flash, or touch launcher/settings/input/account packages.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

VERSION = "0.2.0"
PROFILE_SCHEMA_VERSION = 2
PLAN_VERSION = 1
BACKUP_VERSION = 2

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNAUTHORIZED = 3
EXIT_NO_PROFILE = 4
EXIT_FIRMWARE = 5
EXIT_PARTIAL = 6
EXIT_DEVICE_MISMATCH = 7
EXIT_ENV = 8
EXIT_PLAN = 9

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = ROOT / "profiles"
DEFAULT_TIMEOUT = 25
PLAN_TTL_MINUTES = 15
CORE_BLOCKLIST = {
    "com.mitv.tvhome",
    "com.xiaomi.mitv.settings",
    "com.xiaomi.mitv.tvplayer",
    "com.xiaomi.mitv.tvmanager",
    "com.xiaomi.voicecontrol",
    "com.xiaomi.wakeupservice",
    "com.xiaomi.miplay",
    "com.xiaomi.mitv.smartshare",
    "com.xiaomi.mi_connect_service",
    "com.sohu.inputmethod.sogou.tv",
    "com.xiaomi.account",
    "com.xiaomi.account.auth",
    "com.xiaomi.mitv.appstore",
    "com.xiaomi.mitv.upgrade",
    "com.android.systemui",
    "com.android.settings",
    "com.android.bluetooth",
    "com.android.packageinstaller",
    "com.android.permissioncontroller",
    "com.android.launcher3",
    "mitv.service",
}
CORE_BLOCKLIST_HINT = "桌面、设置、信号源、电视管家、语音、投屏、蓝牙、输入法、账号、商店、OTA"

# The only packages a profile may reference. Adding a package requires changing
# this allowlist plus a test, not just a JSON edit.
ALLOWED_PACKAGES: dict[str, dict[str, Any]] = {
    "com.miui.analytics": {"reason": "系统统计", "risk": "low", "opt_in": False},
    "com.miui.tv.analytics": {"reason": "电视使用统计", "risk": "low", "opt_in": False},
    "com.xiaomi.statistic": {"reason": "埋点统计", "risk": "low", "opt_in": False},
    "com.xiaomi.tvqs": {"reason": "质量/性能上报", "risk": "low", "opt_in": False},
    "com.xiaomi.mitv.tvpush.tvpushservice": {
        "reason": "推送服务（可能影响系统推送）",
        "risk": "medium",
        "opt_in": True,
    },
    "com.mitv.shoplugin": {"reason": "电视淘宝/商城插件", "risk": "low", "opt_in": False},
    "com.mitv.cloudcontrol": {
        "reason": "云端配置下发（可能影响云配置）",
        "risk": "medium",
        "opt_in": True,
    },
    "com.duokan.videodaily": {"reason": "今日头屏/短视频推广", "risk": "low", "opt_in": False},
}

# The only settings a profile may change. Critical keys (adb_enabled,
# device_provisioned, launcher, accessibility, ...) are intentionally absent.
ALLOWED_SETTINGS: dict[tuple[str, str], dict[str, Any]] = {
    ("global", "mitv.settings.advertise.state"): {
        "values": {"0", "1"},
        "risk": "low",
        "opt_in": False,
        "description": "小米广告开关（语义未单变量验证）",
    },
    ("system", "boot_ad_switch"): {
        "values": {"0", "1"},
        "risk": "low",
        "opt_in": False,
        "description": "开机广告开关（外部单机型证据，未在本机验证）",
    },
}

SETTING_NS = {"global", "system", "secure"}
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
STATUS_VALUES = {"draft", "observed", "verified"}
EVIDENCE_VALUES = {"E0", "E1", "E2", "E3"}
RISK_VALUES = {"low", "medium", "high"}

NOT_COVERED = [
    "首页 PatchWall 推荐流（桌面内容）",
    "App 内广告（爱奇艺 / 腾讯 / 优酷等）",
    "会员专属广告",
]


class CliError(Exception):
    """Expected error with a stable exit code and a user-facing message."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# paths / adb
# --------------------------------------------------------------------------- #


def app_home() -> Path:
    raw = os.environ.get("TV_ADS_CLOSE_HOME")
    home = Path(raw).expanduser() if raw else Path.home() / ".tv-ads-close"
    return home


def profile_dir() -> Path:
    raw = os.environ.get("TV_ADS_CLOSE_PROFILES")
    if raw:
        return Path(raw).expanduser()
    candidates = [
        DEFAULT_PROFILE_DIR,
        Path(sys.prefix) / "share" / "tv-ads-close" / "profiles",
        Path.cwd() / "profiles",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return DEFAULT_PROFILE_DIR


def backups_dir() -> Path:
    return app_home() / "backups"


def plans_dir() -> Path:
    return app_home() / "plans"


def locks_dir() -> Path:
    return app_home() / "locks"


def adb_bin() -> str:
    return os.environ.get("ADB", "adb")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def run_adb(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = [adb_bin(), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise CliError(
            EXIT_ENV,
            "找不到 adb。请先安装 Android platform-tools，并确保 adb 在 PATH 中。",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CliError(EXIT_PARTIAL, f"adb 超时：{' '.join(args)}") from exc


def parse_devices(output: str) -> dict[str, str]:
    devices: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices[parts[0]] = parts[1]
    return devices


def connect(host: str) -> None:
    last_error = ""
    for attempt in (1, 2):
        proc = run_adb(["connect", host], timeout=15)
        text = ((proc.stdout or "") + (proc.stderr or "")).lower()
        devices = parse_devices(run_adb(["devices"], timeout=10).stdout)
        state = devices.get(host)
        if state == "device":
            return
        if state == "unauthorized":
            raise CliError(
                EXIT_UNAUTHORIZED,
                "设备未授权：请在电视上允许 USB 调试；不弹窗就重启电视、重开 ADB、保持亮屏后再试。",
            )
        if state == "offline" and attempt == 1:
            last_error = "设备 offline"
            time.sleep(1)
            continue
        if ("failed to connect" in text or "cannot connect" in text) and attempt == 1:
            last_error = "adb connect 失败"
            time.sleep(1)
            continue
        last_error = state or text.strip() or "未知状态"
        if attempt == 2:
            break
    raise CliError(
        EXIT_UNAUTHORIZED,
        f"未找到可调试设备（{host}）：{last_error}。确认电视与电脑同一局域网、ADB 已打开。",
    )


def shell(host: str, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    proc = run_adb(["-s", host, "shell", command], timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CliError(EXIT_PARTIAL, f"设备命令失败：{command}（{detail or 'no output'}）")
    return proc.stdout


def getprop(host: str, prop: str) -> str:
    return shell(host, f"getprop {prop}").strip()


def settings_get(host: str, namespace: str, key: str) -> str | None:
    value = shell(host, f"settings get {namespace} {key}").strip()
    if value in ("", "null"):
        return None
    return value


def settings_put(host: str, namespace: str, key: str, value: str) -> None:
    shell(host, f"settings put {namespace} {key} {shlex.quote(value)}")


def settings_delete(host: str, namespace: str, key: str) -> None:
    shell(host, f"settings delete {namespace} {key}")


def list_packages(host: str, disabled: bool = False) -> set[str]:
    command = "pm list packages -d" if disabled else "pm list packages"
    output = shell(host, command)
    if "error" in output.lower() or "exception" in output.lower():
        raise CliError(EXIT_PARTIAL, f"{command} 返回异常：{output.strip()[:200]}")
    packages = {
        line.strip().removeprefix("package:")
        for line in output.splitlines()
        if line.strip().startswith("package:")
    }
    if not packages and not disabled:
        raise CliError(EXIT_PARTIAL, f"{command} 输出为空；设备可能离线或 pm 不可用。")
    return packages


def serial_hash(serial: str) -> str:
    return hashlib.sha256(("tv-ads-close:v2:" + serial).encode("utf-8")).hexdigest()


def probe(host: str, require_serial: bool = True) -> dict[str, Any]:
    connect(host)
    props = {
        "model": getprop(host, "ro.product.model"),
        "brand": getprop(host, "ro.product.brand"),
        "device": getprop(host, "ro.product.device"),
        "android": getprop(host, "ro.build.version.release"),
        "sdk": getprop(host, "ro.build.version.sdk"),
        "build": getprop(host, "ro.build.display.id"),
    }
    if not props["model"]:
        raise CliError(EXIT_PARTIAL, "无法读取设备型号；请确认设备在线且 adb shell 可用。")
    serial = ""
    for prop in ("ro.serialno", "ro.boot.serialno"):
        value = getprop(host, prop)
        if value and value not in ("unknown", "0"):
            serial = value
            break
    if not serial:
        if require_serial:
            raise CliError(
                EXIT_PARTIAL,
                "无法读取设备序列号（ro.serialno / ro.boot.serialno）。"
                "为防止还原到错误的电视，本工具拒绝继续。",
            )
    packages = list_packages(host)
    disabled = list_packages(host, True)
    return {
        "host": host,
        "model": props["model"],
        "brand": props["brand"],
        "device": props["device"],
        "android": props["android"],
        "sdk": props["sdk"],
        "build": props["build"],
        "serial_hash": serial_hash(serial) if serial else None,
        "serial_tail": serial[-4:] if len(serial) >= 4 else "****",
        "packages": packages,
        "disabled": disabled,
    }


# --------------------------------------------------------------------------- #
# profiles
# --------------------------------------------------------------------------- #


def load_profiles() -> list[dict[str, Any]]:
    directory = profile_dir()
    if not directory.exists():
        raise CliError(EXIT_ENV, f"找不到 profiles 目录：{directory}")
    profiles: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*/*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CliError(EXIT_ENV, f"profile 无法解析：{path}（{exc}）") from exc
        if not isinstance(data, dict):
            raise CliError(EXIT_ENV, f"profile 必须是 JSON 对象：{path}")
        data["_path"] = str(path)
        profiles.append(data)
    if not profiles:
        raise CliError(EXIT_ENV, f"profiles 目录为空：{directory}")
    return profiles


def load_profile(profile_id: str) -> dict[str, Any]:
    for profile in load_profiles():
        if profile.get("id") == profile_id:
            return profile
    raise CliError(EXIT_NO_PROFILE, f"找不到 profile：{profile_id}")


def profile_sha(profile: dict[str, Any]) -> str:
    payload = {k: v for k, v in profile.items() if not k.startswith("_")}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CliError(EXIT_USAGE, message)


def _validate_evidence(evidence: Any, context: str, status: str) -> str:
    _require(isinstance(evidence, dict), f"{context}：evidence 必须是对象")
    level = evidence.get("level")
    _require(level in EVIDENCE_VALUES, f"{context}：evidence.level 必须是 E0–E3")
    for field in ("method", "date"):
        _require(
            isinstance(evidence.get(field), str) and evidence.get(field).strip() != "",
            f"{context}：evidence 缺少 {field}",
        )
    if status == "verified":
        _require(level in {"E2", "E3"}, f"{context}：verified profile 只允许 E2/E3 证据")
        for field in ("before", "after"):
            _require(
                isinstance(evidence.get(field), str) and evidence.get(field).strip() != "",
                f"{context}：verified profile 的 evidence 必须包含 {field}",
            )
    if status == "observed":
        _require(level in {"E1", "E2", "E3"}, f"{context}：observed profile 不允许 E0 动作")
    return level


def validate_profile(profile: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "id",
        "brand",
        "model",
        "device",
        "android",
        "sdk",
        "firmware",
        "status",
        "settings",
        "disable",
        "never_disable",
    ]
    missing = [key for key in required if key not in profile]
    if missing:
        raise CliError(EXIT_USAGE, f"profile 缺少字段：{', '.join(missing)}")
    _require(profile["schema_version"] == PROFILE_SCHEMA_VERSION, "不支持的 profile schema_version")
    _require(isinstance(profile["id"], str) and PROFILE_ID_RE.match(profile["id"]) is not None, "profile.id 格式非法")
    _require(
        isinstance(profile["brand"], str) and profile["brand"].strip() != "",
        "profile.brand 不能为空",
    )
    _require(
        isinstance(profile["model"], str) and profile["model"].strip() != "",
        "profile.model 不能为空",
    )
    _require(
        isinstance(profile["device"], str) and profile["device"].strip() != "",
        "profile.device 不能为空",
    )
    _require(profile["status"] in STATUS_VALUES, "profile.status 必须是 draft/observed/verified")
    _require(isinstance(profile["android"], int), "profile.android 必须是整数")
    _require(isinstance(profile["sdk"], int), "profile.sdk 必须是整数")
    firmware = profile["firmware"]
    _require(isinstance(firmware, list) and firmware and all(isinstance(x, str) and x for x in firmware), "profile.firmware 必须是非空字符串数组")
    _require("*" not in firmware, "profile.firmware 不允许通配符 '*'")
    if profile["status"] == "verified":
        _require(len(firmware) >= 1, "verified profile 必须列出已验证固件")

    never = set(CORE_BLOCKLIST)
    raw_never = profile["never_disable"]
    _require(isinstance(raw_never, list), "profile.never_disable 必须是数组")
    for pkg in raw_never:
        _require(isinstance(pkg, str) and PACKAGE_RE.match(pkg) is not None, f"never_disable 包含非法包名：{pkg}")
        never.add(pkg)

    settings = profile["settings"]
    _require(isinstance(settings, dict), "profile.settings 必须是对象")
    seen_settings: set[tuple[str, str]] = set()
    for namespace, values in settings.items():
        _require(namespace in SETTING_NS, f"非法 settings namespace：{namespace}")
        _require(isinstance(values, dict) and values, f"settings.{namespace} 不能为空")
        for key, spec in values.items():
            _require(isinstance(key, str) and (namespace, key) in ALLOWED_SETTINGS, f"不在安全键表内的 setting：{namespace}/{key}")
            _require((namespace, key) not in seen_settings, f"重复的 setting：{namespace}/{key}")
            seen_settings.add((namespace, key))
            _require(isinstance(spec, dict), f"setting {namespace}/{key} 必须是对象")
            allowed = ALLOWED_SETTINGS[(namespace, key)]
            value = str(spec.get("value", ""))
            _require(value in allowed["values"], f"setting {namespace}/{key} 的值不在允许范围：{value!r}")
            _require(isinstance(spec.get("reason"), str) and spec["reason"].strip(), f"setting {namespace}/{key} 缺少 reason")
            risk = spec.get("risk")
            _require(risk in {"low", "medium"}, f"setting {namespace}/{key} 的 risk 必须是 low/medium")
            if risk == "medium":
                _require(spec.get("opt_in") is True, f"setting {namespace}/{key} 为 medium 时必须 opt_in=true")
            _validate_evidence(spec.get("evidence"), f"setting {namespace}/{key}", profile["status"])

    disable = profile["disable"]
    _require(isinstance(disable, list), "profile.disable 必须是数组")
    _require(len(disable) > 0, "profile.disable 不能为空（draft 也至少列出一个候选）")
    seen_packages: set[str] = set()
    for item in disable:
        _require(isinstance(item, dict), "disable 项必须是对象")
        pkg = item.get("package")
        _require(isinstance(pkg, str) and PACKAGE_RE.match(pkg) is not None, f"非法包名：{pkg}")
        _require(pkg not in seen_packages, f"重复包：{pkg}")
        seen_packages.add(pkg)
        _require(pkg in ALLOWED_PACKAGES, f"不在 allowlist 内的包：{pkg}")
        _require(pkg not in never and pkg not in CORE_BLOCKLIST, f"拒绝：核心包不能停用（{pkg}）")
        allowed = ALLOWED_PACKAGES[pkg]
        _require(isinstance(item.get("reason"), str) and item["reason"].strip(), f"{pkg} 缺少 reason")
        risk = item.get("risk")
        _require(risk in {"low", "medium"}, f"{pkg} 的 risk 必须是 low/medium")
        if risk == "medium" or allowed["opt_in"]:
            _require(item.get("opt_in") is True, f"{pkg} 为 medium/opt-in 时必须 opt_in=true")
        _validate_evidence(item.get("evidence"), pkg, profile["status"])


def match_profile(profiles: list[dict[str, Any]], info: dict[str, Any]) -> dict[str, Any]:
    exact: list[dict[str, Any]] = []
    model_matches: list[dict[str, Any]] = []
    invalid: list[str] = []
    for profile in profiles:
        try:
            validate_profile(profile)
        except CliError as exc:
            invalid.append(f"{profile.get('id', '?')}: {exc.message}")
            continue
        if profile["model"].lower() != info["model"].lower():
            continue
        model_matches.append(profile)
        if (
            profile["device"].lower() == (info["device"] or "").lower()
            and profile["brand"].lower() == (info["brand"] or "").lower()
            and str(profile["android"]) == str(info["android"])
            and str(profile["sdk"]) == str(info["sdk"])
            and info["build"] in profile["firmware"]
        ):
            exact.append(profile)
    if exact:
        return exact[0]
    if invalid and not model_matches:
        raise CliError(EXIT_ENV, "没有可用 profile（校验失败）：" + "；".join(invalid))
    if model_matches:
        raise CliError(
            EXIT_FIRMWARE,
            f"机型匹配但固件/代号/系统版本未验证：{info['model']} / {info['build']}。"
            "请停止操作，按 CONTRIBUTING.md 提交机型报告。",
        )
    raise CliError(
        EXIT_NO_PROFILE,
        f"没有匹配的 profile：{info['model'] or '未知型号'}。"
        "请停止操作，按 CONTRIBUTING.md 提交机型报告。",
    )


def check_profile_device(profile: dict[str, Any], info: dict[str, Any]) -> None:
    checks = {
        "model": (profile["model"], info["model"]),
        "device": (profile["device"], info["device"]),
        "brand": (profile["brand"], info["brand"]),
        "android": (str(profile["android"]), str(info["android"])),
        "sdk": (str(profile["sdk"]), str(info["sdk"])),
    }
    for name, (expected, actual) in checks.items():
        if name == "model" and str(expected).lower() == str(actual).lower():
            continue
        if str(expected) != str(actual):
            raise CliError(
                EXIT_DEVICE_MISMATCH,
                f"profile 与设备不一致（{name}）：profile={expected!r}，设备={actual!r}。",
            )
    if info["build"] not in profile["firmware"]:
        raise CliError(EXIT_FIRMWARE, f"固件未验证：{info['build']}")


def canonical_actions(actions: list[dict[str, Any]]) -> str:
    raw = json.dumps(actions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def plan_integrity(plan: dict[str, Any]) -> str:
    payload = {k: v for k, v in plan.items() if k not in ("integrity", "plan_signature")}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def select_actions(
    profile: dict[str, Any], include_observed: bool, include_risky: bool
) -> list[dict[str, Any]]:
    if profile["status"] == "draft":
        raise CliError(EXIT_NO_PROFILE, "该 profile 仍是 draft，不能执行。")
    actions: list[dict[str, Any]] = []
    for namespace in ("global", "system", "secure"):
        for key in sorted(profile["settings"].get(namespace, {})):
            spec = profile["settings"][namespace][key]
            level = spec["evidence"]["level"]
            if level == "E0":
                continue
            if level == "E1" and not include_observed:
                continue
            if spec.get("risk") == "medium" and not include_risky:
                continue
            actions.append(
                {
                    "type": "setting",
                    "namespace": namespace,
                    "key": key,
                    "value": str(spec["value"]),
                    "reason": spec["reason"],
                    "risk": spec["risk"],
                    "evidence": level,
                }
            )
    for item in sorted(profile["disable"], key=lambda x: x["package"]):
        level = item["evidence"]["level"]
        if level == "E0":
            continue
        if level == "E1" and not include_observed:
            continue
        if (item.get("risk") == "medium" or item.get("opt_in")) and not include_risky:
            continue
        actions.append(
            {
                "type": "disable",
                "package": item["package"],
                "reason": item["reason"],
                "risk": item["risk"],
                "opt_in": bool(item.get("opt_in")),
                "evidence": level,
            }
        )
    return actions


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #


def build_plan(
    profile: dict[str, Any],
    info: dict[str, Any],
    actions: list[dict[str, Any]],
    include_observed: bool,
    include_risky: bool,
) -> dict[str, Any]:
    if not actions:
        raise CliError(
            EXIT_USAGE,
            "该 profile 在当前证据级别下没有可执行动作。"
            "若是单机观察级（E1），需显式加 --include-observed 预演；"
            "含中风险动作时还需 --include-risky。",
        )
    plan_id = uuid.uuid4().hex
    created = now_utc()
    plan = {
        "plan_version": PLAN_VERSION,
        "plan_id": plan_id,
        "confirm_code": plan_id[:8],
        "created_at": iso(created),
        "expires_at": iso(created + timedelta(minutes=PLAN_TTL_MINUTES)),
        "tool_version": VERSION,
        "host": info["host"],
        "device": {
            "model": info["model"],
            "brand": info["brand"],
            "device": info["device"],
            "android": str(info["android"]),
            "sdk": str(info["sdk"]),
            "build": info["build"],
            "serial_hash": info["serial_hash"],
            "serial_tail": info["serial_tail"],
        },
        "profile": {
            "id": profile["id"],
            "status": profile["status"],
            "sha256": profile_sha(profile),
        },
        "flags": {
            "include_observed": include_observed,
            "include_risky": include_risky,
        },
        "actions": actions,
        "action_hash": canonical_actions(actions),
        "not_covered": NOT_COVERED,
        "warnings": [],
    }
    if profile["status"] == "observed":
        plan["warnings"].append(
            "该 profile 是单机观察级（E1）：只在一台电视上执行过，未做单变量对照；"
            "不能视为已全面验证。"
        )
    if any(a["evidence"] == "E1" for a in actions):
        plan["warnings"].append("计划包含 E1 动作：效果有观察，但未隔离变量。")
    if any(a.get("risk") == "medium" for a in actions):
        plan["warnings"].append("计划包含中风险动作：可能影响系统推送/云配置。")
    plan["integrity"] = plan_integrity(plan)
    return plan


def write_json_atomic(path: Path, data: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_text_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def backup_key_path() -> Path:
    return app_home() / "backup.key"


def plan_key_path() -> Path:
    return app_home() / "plan.key"


def _load_key_file(path: Path, label: str, create: bool = False) -> str:
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
        if len(key) < 32:
            raise CliError(EXIT_ENV, f"{label}密钥损坏：{path}")
        try:
            mode = path.stat().st_mode & 0o777
            if mode & 0o077:
                os.chmod(path, 0o600)
        except OSError as exc:
            raise CliError(EXIT_ENV, f"{label}密钥权限无法收紧：{path}（{exc}）") from exc
        return key
    if not create:
        raise CliError(EXIT_ENV, f"找不到{label}密钥：{path}；无法验证来源。")
    key = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _load_key_file(path, label, create=False)
    try:
        os.write(fd, (key + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return key


def load_backup_key(create: bool = False) -> str:
    return _load_key_file(backup_key_path(), "备份签名", create)


def load_plan_key(create: bool = False) -> str:
    return _load_key_file(plan_key_path(), "计划签名", create)


def canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sign_backup(state: dict[str, Any]) -> dict[str, Any]:
    key = load_backup_key(create=True)
    payload = {k: v for k, v in state.items() if k != "signature"}
    state["signature"] = hmac.new(
        key.encode("utf-8"), canonical_payload(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return state


def verify_backup_signature(backup: dict[str, Any]) -> None:
    signature = backup.get("signature")
    if not isinstance(signature, str):
        raise CliError(EXIT_USAGE, "备份缺少签名，拒绝还原。")
    key = load_backup_key(create=False)
    payload = {k: v for k, v in backup.items() if k != "signature"}
    expected = hmac.new(
        key.encode("utf-8"), canonical_payload(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise CliError(EXIT_USAGE, "备份签名无效（可能被修改或来自其他机器），拒绝还原。")


def sign_plan(plan: dict[str, Any]) -> dict[str, Any]:
    key = load_plan_key(create=True)
    payload = {k: v for k, v in plan.items() if k != "plan_signature"}
    plan["plan_signature"] = hmac.new(
        key.encode("utf-8"), canonical_payload(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return plan


def verify_plan_signature(plan: dict[str, Any]) -> None:
    signature = plan.get("plan_signature")
    if not isinstance(signature, str):
        raise CliError(EXIT_PLAN, "计划缺少签名，拒绝使用。")
    key = load_plan_key(create=False)
    payload = {k: v for k, v in plan.items() if k != "plan_signature"}
    expected = hmac.new(
        key.encode("utf-8"), canonical_payload(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise CliError(EXIT_PLAN, "计划签名无效（可能被修改或来自其他机器），请重新运行 plan。")


def save_plan(plan: dict[str, Any], target: str | None) -> Path:
    if target:
        path = Path(target).expanduser().resolve()
    else:
        path = plans_dir() / f"{plan['plan_id']}.json"
    write_json_atomic(path, sign_plan(plan))
    return path


def load_plan(path: str) -> dict[str, Any]:
    plan_path = Path(path).expanduser()
    if not plan_path.is_file():
        raise CliError(EXIT_PLAN, f"找不到计划文件：{path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(EXIT_PLAN, f"计划文件无法解析：{path}（{exc}）") from exc
    if not isinstance(plan, dict) or plan.get("plan_version") != PLAN_VERSION:
        raise CliError(EXIT_PLAN, "计划文件版本不支持，请重新运行 plan。")
    verify_plan_signature(plan)
    required = (
        "plan_id",
        "confirm_code",
        "expires_at",
        "host",
        "device",
        "profile",
        "flags",
        "actions",
        "action_hash",
        "not_covered",
        "warnings",
    )
    if any(key not in plan for key in required):
        raise CliError(EXIT_PLAN, "计划文件字段不完整，请重新运行 plan。")
    if (
        not isinstance(plan["actions"], list)
        or not all(isinstance(action, dict) for action in plan["actions"])
        or not isinstance(plan["device"], dict)
        or not isinstance(plan["profile"], dict)
        or not isinstance(plan["profile"].get("id"), str)
        or not isinstance(plan["flags"], dict)
        or not isinstance(plan["not_covered"], list)
        or not all(isinstance(item, str) for item in plan["not_covered"])
        or not isinstance(plan["warnings"], list)
        or not all(isinstance(item, str) for item in plan["warnings"])
        or not isinstance(plan["host"], str)
        or not isinstance(plan["expires_at"], str)
        or not isinstance(plan["plan_id"], str)
        or not isinstance(plan["confirm_code"], str)
    ):
        raise CliError(EXIT_PLAN, "计划文件结构不正确，请重新运行 plan。")
    if plan.get("integrity") != plan_integrity(plan):
        raise CliError(EXIT_PLAN, "计划文件被修改（完整性校验失败），请重新运行 plan。")
    return plan


def verify_plan(
    plan: dict[str, Any], profile: dict[str, Any], info: dict[str, Any], check_expiry: bool = True
) -> None:
    try:
        expires = datetime.fromisoformat(plan["expires_at"])
        if expires.tzinfo is None:
            raise ValueError("naive datetime")
    except (KeyError, ValueError, TypeError) as exc:
        raise CliError(EXIT_PLAN, "计划文件缺少有效的 expires_at。") from exc
    if check_expiry and now_utc() > expires:
        raise CliError(EXIT_PLAN, "计划已过期，请重新运行 plan。")
    if plan.get("tool_version") != VERSION:
        raise CliError(EXIT_PLAN, "计划由其他版本的工具生成，请重新运行 plan。")
    validate_profile(profile)
    check_profile_device(profile, info)
    for action in plan.get("actions", []):
        assert_action_allowed(action)
    if plan["profile"]["sha256"] != profile_sha(profile):
        raise CliError(EXIT_PLAN, "profile 在 plan 之后被修改，请重新运行 plan。")
    flags = plan.get("flags", {})
    expected = select_actions(
        profile, bool(flags.get("include_observed")), bool(flags.get("include_risky"))
    )
    if canonical_actions(expected) != plan.get("action_hash"):
        raise CliError(EXIT_PLAN, "计划内容与 profile 不一致（可能被手改），拒绝执行。")
    if plan.get("actions") != expected:
        raise CliError(EXIT_PLAN, "计划动作列表被修改，拒绝执行。")
    device = plan.get("device", {})
    for key in ("model", "brand", "device", "android", "sdk", "build", "serial_hash"):
        if str(device.get(key)) != str(info.get(key)):
            raise CliError(
                EXIT_DEVICE_MISMATCH,
                f"计划与当前设备不一致（{key}）：计划={device.get(key)!r}，当前={info.get(key)!r}。"
                "请重新 probe + plan。",
            )


# --------------------------------------------------------------------------- #
# state capture / backup / journal
# --------------------------------------------------------------------------- #


def capture_state(
    host: str,
    info: dict[str, Any],
    setting_pairs: list[tuple[str, str]],
    packages: list[str],
    kind: str,
) -> dict[str, Any]:
    settings: dict[str, dict[str, Any]] = {}
    for namespace, key in setting_pairs:
        value = settings_get(host, namespace, key)
        settings.setdefault(namespace, {})[key] = {"present": value is not None, "value": value}
    package_state: dict[str, dict[str, Any]] = {}
    for pkg in packages:
        package_state[pkg] = {
            "installed": pkg in info["packages"],
            "was_disabled": pkg in info["disabled"],
        }
    return {
        "backup_version": BACKUP_VERSION,
        "tool_version": VERSION,
        "created_at": iso(now_utc()),
        "kind": kind,
        "device": {
            "model": info["model"],
            "brand": info["brand"],
            "device": info["device"],
            "android": str(info["android"]),
            "sdk": str(info["sdk"]),
            "build": info["build"],
            "serial_hash": info["serial_hash"],
            "serial_tail": info["serial_tail"],
        },
        "settings": settings,
        "packages": package_state,
    }


def backup_paths(info: dict[str, Any], make_baseline: bool) -> tuple[Path, Path | None]:
    directory = backups_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%d-%H%M%S")
    serial_part = (info.get("serial_hash") or "noserial")[:8]
    suffix = f"{serial_part}-{uuid.uuid4().hex[:6]}"
    path = directory / f"{stamp}-{suffix}.json"
    baseline = directory / f"baseline-{serial_part}.json"
    if not make_baseline or baseline.exists():
        baseline = None
    return path, baseline


def write_backup(
    info: dict[str, Any], state: dict[str, Any], make_baseline: bool
) -> tuple[Path, Path | None]:
    path, baseline = backup_paths(info, make_baseline)
    state = sign_backup(state)
    write_json_atomic(path, state)
    if baseline is not None:
        write_json_atomic(baseline, state)
    return path, baseline


def acquire_lock(info: dict[str, Any]) -> Path:
    directory = locks_dir()
    directory.mkdir(parents=True, exist_ok=True)
    serial_part = (info.get("serial_hash") or "noserial")[:16]
    path = directory / f"{serial_part}.lock"
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < 2 * 3600:
            raise CliError(EXIT_PARTIAL, f"另一个进程正在操作这台电视（锁文件：{path}）。")
        path.unlink()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, f"{os.getpid()} {iso(now_utc())}\n".encode("utf-8"))
    finally:
        os.close(fd)
    return path


def release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def journal_path(backup: Path) -> Path:
    return backup.with_name(backup.name.replace(".json", ".journal.json"))


def write_journal(backup: Path, journal: dict[str, Any]) -> None:
    write_json_atomic(journal_path(backup), journal)


# --------------------------------------------------------------------------- #
# apply / restore
# --------------------------------------------------------------------------- #


def assert_action_allowed(action: dict[str, Any]) -> None:
    kind = action.get("type")
    if kind == "setting":
        namespace = action.get("namespace")
        key = action.get("key")
        if not isinstance(namespace, str) or not isinstance(key, str):
            raise CliError(EXIT_PLAN, "动作的 namespace/key 类型非法。")
        value = str(action.get("value", ""))
        if (namespace, key) not in ALLOWED_SETTINGS:
            raise CliError(EXIT_PLAN, f"动作包含不在安全键表内的设置：{namespace}/{key}")
        if value not in ALLOWED_SETTINGS[(namespace, key)]["values"]:
            raise CliError(EXIT_PLAN, f"动作设置值非法：{namespace}/{key}={value!r}")
        return
    if kind == "disable":
        pkg = action.get("package")
        if not isinstance(pkg, str) or PACKAGE_RE.match(pkg) is None:
            raise CliError(EXIT_PLAN, f"动作包含非法包名：{pkg!r}")
        if pkg not in ALLOWED_PACKAGES or pkg in CORE_BLOCKLIST:
            raise CliError(EXIT_PLAN, f"动作包含不允许停用的包：{pkg}")
        return
    raise CliError(EXIT_PLAN, f"未知动作类型：{kind!r}")


def execute_action(host: str, info: dict[str, Any], action: dict[str, Any]) -> str:
    assert_action_allowed(action)
    if action["type"] == "setting":
        namespace, key, value = action["namespace"], action["key"], action["value"]
        settings_put(host, namespace, key, value)
        actual = settings_get(host, namespace, key)
        if actual != value:
            raise CliError(EXIT_PARTIAL, f"设置未生效：{namespace}/{key} 期望 {value!r}，实际 {actual!r}")
        return "ok"
    if action["type"] == "disable":
        pkg = action["package"]
        if pkg not in info["packages"]:
            return "not_installed"
        if pkg in info["disabled"]:
            return "already_disabled"
        shell(host, f"pm disable-user --user 0 {shlex.quote(pkg)}")
        disabled_now = list_packages(host, True)
        if pkg not in disabled_now:
            raise CliError(EXIT_PARTIAL, f"停用未生效：{pkg}")
        info["disabled"] = disabled_now
        return "disabled_now"
    raise CliError(EXIT_PARTIAL, f"未知动作类型：{action.get('type')}")


def verify_actions(host: str, info: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for action in actions:
        if action["type"] == "setting":
            actual = settings_get(host, action["namespace"], action["key"])
            if actual != action["value"]:
                failures.append(f"{action['namespace']}/{action['key']} 期望 {action['value']!r}，实际 {actual!r}")
        else:
            pkg = action["package"]
            if pkg in list_packages(host, True):
                continue
            if pkg not in info["packages"]:
                continue
            failures.append(f"{pkg} 仍处于启用状态")
    return failures


def core_regression(host: str, core_before: set[str]) -> list[str]:
    now_disabled = list_packages(host, True)
    problems: list[str] = []
    for pkg in CORE_BLOCKLIST:
        if pkg in now_disabled and pkg not in core_before:
            problems.append(f"核心包被停用：{pkg}")
    return problems


def mask_host(host: str) -> str:
    base = host.split(":")[0]
    parts = base.split(".")
    if len(parts) == 4:
        return ".".join(parts[:-1] + ["x"])
    return base


def format_restore_command(host: str, backup: Path) -> str:
    return (
        "python3 scripts/tv_ads_close.py restore "
        f"--host {shlex.quote(host)} --backup {shlex.quote(str(backup))} --attest-owner"
    )


def apply_plan(
    plan: dict[str, Any],
    profile: dict[str, Any],
    info: dict[str, Any],
    host: str,
    confirm: str,
    no_auto_restore: bool,
) -> None:
    if confirm.strip().lower() != str(plan["confirm_code"]).lower():
        raise CliError(EXIT_USAGE, "确认码不匹配。确认码是 plan 输出中的 8 位十六进制。")
    verify_plan(plan, profile, info)
    lock = acquire_lock(info)
    backup: Path | None = None
    try:
        # Re-probe under the lock: the IP may now point at another TV.
        info = probe(host)
        verify_plan(plan, profile, info)
        core_before = set(CORE_BLOCKLIST) & set(info["disabled"])
        setting_pairs = [
            (namespace, key)
            for namespace in ("global", "system", "secure")
            for key in profile["settings"].get(namespace, {})
        ]
        packages = [item["package"] for item in profile["disable"]]
        state = capture_state(host, info, setting_pairs, packages, "pre-apply")
        backup, baseline = write_backup(info, state, make_baseline=True)
        journal = {
            "plan_id": plan["plan_id"],
            "backup": str(backup),
            "started_at": iso(now_utc()),
            "status": "running",
            "actions": [],
        }
        write_journal(backup, journal)
        print(f"备份已写入：{backup}")
        if baseline is not None:
            print(f"（首次执行，另存 baseline：{baseline}）")
        failures = 0
        for index, action in enumerate(plan["actions"], start=1):
            label = (
                f"{action['namespace']}/{action['key']}"
                if action["type"] == "setting"
                else action["package"]
            )
            try:
                status = execute_action(host, info, action)
            except (CliError, KeyboardInterrupt) as exc:
                journal["status"] = "failed"
                journal["actions"].append(
                    {"index": index, "label": label, "status": "failed", "detail": str(exc)}
                )
                write_journal(backup, journal)
                print(f"[FAIL] {label}  {exc}")
                if not no_auto_restore:
                    print("\n检测到失败，正在自动回滚……")
                    try:
                        restore_from_backup(host, backup, dry_run=False, force=False, quiet=True)
                        print("自动回滚完成。")
                    except CliError as restore_error:
                        print(f"自动回滚失败：{restore_error.message}")
                        print(f"请手动执行：{format_restore_command(host, backup)}")
                if isinstance(exc, KeyboardInterrupt):
                    raise
                raise
            journal["actions"].append({"index": index, "label": label, "status": status})
            write_journal(backup, journal)
            print(f"[OK] {label}  {status}")
        try:
            failures = len(verify_actions(host, info, plan["actions"]))
            problems = core_regression(host, core_before)
        except CliError as exc:
            journal["status"] = "failed"
            write_journal(backup, journal)
            print(f"[FAIL] 验证阶段出错：{exc}")
            if not no_auto_restore:
                print("\n验证阶段出错，正在自动回滚……")
                try:
                    restore_from_backup(host, backup, dry_run=False, force=False, quiet=True)
                    print("自动回滚完成。")
                except Exception as restore_error:  # noqa: BLE001 - keep original error visible
                    print(f"自动回滚失败：{restore_error}")
                    print(f"请手动执行：{format_restore_command(host, backup)}")
            raise
        if failures or problems:
            journal["status"] = "failed"
            write_journal(backup, journal)
            for item in failures + problems:
                print(f"[FAIL] {item}")
            if not no_auto_restore:
                print("\n验证未通过，正在自动回滚……")
                restore_from_backup(host, backup, dry_run=False, force=False, quiet=True)
            raise CliError(EXIT_PARTIAL, "执行后验证失败，已停止。")
        journal["status"] = "applied"
        write_journal(backup, journal)
    finally:
        release_lock(lock)

    print("\n完成。")
    print(f"计划：{plan['plan_id']}（确认码 {plan['confirm_code']}）")
    print(f"设备：{info['brand']} {info['model']} / Android {info['android']} / {info['build']}")
    print(f"备份：{backup}")
    print(f"回滚：{format_restore_command(host, backup)}")
    print("未覆盖：" + "、".join(plan["not_covered"]))
    print("验证：先运行 verify 检查设置/包状态；然后重启电视观察开机过程。")
    print("安全：完成后请到 设置 → 账号与安全 → ADB 调试 关闭 ADB（5555 是明文端口）。")


def _validate_backup(backup: dict[str, Any]) -> None:
    if not isinstance(backup, dict):
        raise CliError(EXIT_USAGE, "备份文件必须是 JSON 对象。")
    if backup.get("backup_version") != BACKUP_VERSION:
        raise CliError(EXIT_USAGE, "备份文件版本不支持。")
    for key in ("device", "settings", "packages"):
        if key not in backup:
            raise CliError(EXIT_USAGE, f"备份文件缺少 {key}。")
    if not isinstance(backup["device"], dict) or not isinstance(backup["settings"], dict) or not isinstance(backup["packages"], dict):
        raise CliError(EXIT_USAGE, "备份文件结构不正确。")
    for namespace, values in backup["settings"].items():
        if not isinstance(values, dict):
            raise CliError(EXIT_USAGE, f"备份 settings.{namespace} 结构不正确。")
        if namespace not in SETTING_NS:
            raise CliError(EXIT_USAGE, f"备份包含非法 namespace：{namespace}")
        for key, item in values.items():
            if (namespace, key) not in ALLOWED_SETTINGS:
                raise CliError(EXIT_USAGE, f"备份包含不在安全键表内的设置：{namespace}/{key}")
            if not isinstance(item, dict) or not isinstance(item.get("present"), bool):
                raise CliError(EXIT_USAGE, f"备份设置格式错误：{namespace}/{key}")
            if item["present"]:
                value = item.get("value")
                if not isinstance(value, str) or len(value) > 256 or any(ord(ch) < 32 for ch in value):
                    raise CliError(EXIT_USAGE, f"备份设置值格式非法：{namespace}/{key}")
    for pkg, state in backup["packages"].items():
        if pkg not in ALLOWED_PACKAGES:
            raise CliError(EXIT_USAGE, f"备份包含不在 allowlist 内的包：{pkg}")
        if not isinstance(state, dict) or not isinstance(state.get("installed"), bool) or not isinstance(state.get("was_disabled"), bool):
            raise CliError(EXIT_USAGE, f"备份包状态格式错误：{pkg}")


def restore_from_backup(
    host: str, backup_path: Path, dry_run: bool, force: bool, quiet: bool = False
) -> None:
    if not backup_path.is_file():
        raise CliError(EXIT_USAGE, f"找不到备份：{backup_path}")
    try:
        backup = json.loads(backup_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(EXIT_USAGE, f"备份无法解析：{backup_path}（{exc}）") from exc
    if not isinstance(backup, dict):
        raise CliError(EXIT_USAGE, "备份文件必须是 JSON 对象。")
    verify_backup_signature(backup)
    _validate_backup(backup)
    info = probe(host, require_serial=False)
    device = backup["device"]
    backup_serial = device.get("serial_hash")
    current_serial = info.get("serial_hash")
    serial_ok = bool(backup_serial) and bool(current_serial) and backup_serial == current_serial
    if not serial_ok or str(device.get("model")) != str(info["model"]):
        if not force:
            raise CliError(
                EXIT_DEVICE_MISMATCH,
                "备份不属于当前设备（序列号/型号不匹配），拒绝还原。"
                "如确认要强制还原，请加 --force-device-mismatch。",
            )
    if not dry_run:
        pre, _ = write_backup(
            info,
            capture_state(
                host,
                info,
                [(ns, key) for ns, values in backup["settings"].items() for key in values],
                list(backup["packages"]),
                "pre-restore",
            ),
            make_baseline=False,
        )
        if not quiet:
            print(f"还原前备份：{pre}")
    failures: list[str] = []
    for pkg, state in backup["packages"].items():
        if not state.get("installed"):
            if not quiet:
                print(f"[SKIP] {pkg}  未安装")
            continue
        currently_disabled = pkg in list_packages(host, True)
        want_disabled = bool(state.get("was_disabled"))
        if currently_disabled == want_disabled:
            if not quiet:
                print(f"[OK] {pkg}  已是目标状态")
            continue
        quoted = shlex.quote(pkg)
        command = f"pm disable-user --user 0 {quoted}" if want_disabled else f"pm enable --user 0 {quoted}"
        if dry_run:
            if not quiet:
                print(f"[DRY] {command}")
            continue
        shell(host, command)
        if (pkg in list_packages(host, True)) != want_disabled:
            failures.append(f"{pkg} 还原失败")
            if not quiet:
                print(f"[FAIL] {pkg}")
        elif not quiet:
            print(f"[OK] {pkg}")
    for namespace, values in backup["settings"].items():
        for key, item in values.items():
            command: str
            if item["present"]:
                command = f"settings put {namespace} {key} {shlex.quote(str(item['value']))}"
            else:
                command = f"settings delete {namespace} {key}"
            if dry_run:
                if not quiet:
                    print(f"[DRY] {command}")
                continue
            shell(host, command)
            actual = settings_get(host, namespace, key)
            expected = str(item["value"]) if item["present"] else None
            if actual != expected:
                failures.append(f"{namespace}/{key} 还原失败（期望 {expected!r}，实际 {actual!r}）")
                if not quiet:
                    print(f"[FAIL] {namespace}/{key}")
            elif not quiet:
                print(f"[OK] {namespace}/{key}")
    if failures:
        raise CliError(EXIT_PARTIAL, "还原未完全成功：" + "；".join(failures))
    if not quiet:
        print("\n还原完成。建议重启电视后再检查。")


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #


def print_plan(plan: dict[str, Any], plan_path: Path | None = None, demo: bool = False) -> None:
    device = plan["device"]
    profile = plan["profile"]
    print(f"设备：{device['brand']} {device['model']} / Android {device['android']} / {device['build']}")
    print(f"序列号：***{device['serial_tail']}    来源 IP：{mask_host(plan['host'])}")
    print(f"Profile：{profile['id']}（状态：{profile['status']}）")
    if demo:
        print("样例（不可执行）：不生成确认码，也不会执行；真实 plan 才产生计划文件。")
    else:
        print(f"计划 ID：{plan['plan_id'][:12]}…    确认码：{plan['confirm_code']}    15 分钟内有效")
    print("将执行：")
    for action in plan["actions"]:
        if action["type"] == "setting":
            print(
                f"  [settings] {action['namespace']}/{action['key']} = {action['value']}"
                f"  # {action['reason']}（{action['evidence']} / {action['risk']}）"
            )
        else:
            opt = "，opt-in" if action.get("opt_in") else ""
            print(
                f"  [disable] {action['package']}  # {action['reason']}"
                f"（{action['evidence']} / {action['risk']}{opt}）"
            )
    for warning in plan.get("warnings", []):
        print(f"⚠️  {warning}")
    print("未覆盖：" + "、".join(plan["not_covered"]))
    print("回滚：apply 会先生成备份并打印完整 restore 命令；执行前不需要回滚。")
    if demo:
        print("\nDemo 不生成计划文件，也不会执行 apply。")
        return
    print("\n下一步：把上面的计划展示给设备所有人；确认后执行：")
    target = plan_path if plan_path else plans_dir() / f"{plan['plan_id']}.json"
    print(
        f"  python3 scripts/tv_ads_close.py apply --plan {shlex.quote(str(target))} "
        f"--confirm {plan['confirm_code']} --attest-owner"
    )


def print_probe(info: dict[str, Any]) -> None:
    print(f"{info['brand']} {info['model']} / {info['device']} / Android {info['android']}（SDK {info['sdk']}）")
    print(f"固件：{info['build']}    序列号：***{info['serial_tail']}    IP：{mask_host(info['host'])}")
    print(f"已安装包：{len(info['packages'])}    已停用包：{len(info['disabled'])}")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def require_owner(args: argparse.Namespace) -> None:
    if not getattr(args, "attest_owner", False):
        raise CliError(
            EXIT_USAGE,
            "必须加 --attest-owner，确认这是你本人拥有的设备，"
            "或设备所有人在场并明确同意。",
        )


def cmd_demo(args: argparse.Namespace) -> int:
    profiles = load_profiles()
    validate_profile(profiles[0])
    profile = profiles[0]
    fake_info = {
        "host": "demo",
        "model": profile["model"],
        "brand": profile["brand"],
        "device": profile["device"],
        "android": str(profile["android"]),
        "sdk": str(profile["sdk"]),
        "build": profile["firmware"][0],
        "serial_hash": "0" * 64,
        "serial_tail": "DEMO",
        "packages": {item["package"] for item in profile["disable"]},
        "disabled": set(),
    }
    actions = select_actions(profile, include_observed=True, include_risky=False)
    plan = build_plan(profile, fake_info, actions, True, False)
    print("== Demo：假设备数据，不会连接任何设备，也不会执行命令 ==\n")
    print_plan(plan, demo=True)
    print("\n说明：Demo 只演示 E1 + 低风险动作；中风险动作需 --include-risky。")
    print("真实 plan 在 observed profile 上默认拒绝（无动作，退出码 2）。")
    print("\nDemo 结束。")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"Python：{sys.version.split()[0]}")
    print(f"平台：{sys.platform}")
    proc = run_adb(["version"], timeout=10)
    if proc.returncode != 0:
        raise CliError(EXIT_ENV, "adb 不可用：" + (proc.stderr or proc.stdout).strip())
    print(f"adb：{adb_bin()}")
    print((proc.stdout or proc.stderr).strip().splitlines()[0])
    try:
        backups_dir().mkdir(parents=True, exist_ok=True)
        probe_file = backups_dir() / ".write-test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        print(f"备份目录：{backups_dir()}（可写）")
    except OSError as exc:
        raise CliError(EXIT_ENV, f"备份目录不可写：{exc}") from exc
    profiles = load_profiles()
    valid = 0
    for profile in profiles:
        try:
            validate_profile(profile)
            valid += 1
        except CliError as exc:
            print(f"  ✗ {profile.get('id')}: {exc.message}")
    print(f"profiles：{valid}/{len(profiles)} 通过校验")
    for label, path in (("备份签名", backup_key_path()), ("计划签名", plan_key_path())):
        if path.exists():
            mode = path.stat().st_mode & 0o777
            print(f"{label}：{path}（权限 {oct(mode)}）")
        else:
            print(f"{label}：未创建（首次备份/计划时生成）")
    if valid == 0:
        raise CliError(EXIT_ENV, "没有任何有效 profile。")
    return EXIT_OK


def cmd_probe(args: argparse.Namespace) -> int:
    info = probe(normalize_host(args.host))
    if args.json:
        payload = {
            k: v for k, v in info.items() if k not in {"packages", "disabled", "serial_hash"}
        }
        payload["host"] = mask_host(info["host"])
        payload["package_count"] = len(info["packages"])
        payload["disabled_count"] = len(info["disabled"])
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_probe(info)
    return EXIT_OK


def cmd_plan(args: argparse.Namespace) -> int:
    require_owner(args)
    host = normalize_host(args.host)
    info = probe(host)
    profiles = load_profiles()
    profile = match_profile(profiles, info) if args.profile in (None, "auto") else load_profile(args.profile)
    validate_profile(profile)
    if args.profile not in (None, "auto"):
        check_profile_device(profile, info)
    actions = select_actions(profile, args.include_observed, args.include_risky)
    plan = build_plan(profile, info, actions, args.include_observed, args.include_risky)
    target = args.save if args.save not in (None, "__DEFAULT__") else None
    path = save_plan(plan, target)
    if args.json:
        display = json.loads(json.dumps(plan))
        display["host"] = mask_host(display.get("host", ""))
        display["device"]["serial_hash"] = "***"
        print(json.dumps(display, ensure_ascii=False, indent=2))
    else:
        print_plan(plan, path)
        print(f"\n计划文件：{path}")
    return EXIT_OK


def cmd_apply(args: argparse.Namespace) -> int:
    require_owner(args)
    plan = load_plan(args.plan)
    profile = load_profile(plan["profile"]["id"])
    validate_profile(profile)
    host = normalize_host(args.host) if args.host else plan["host"]
    info = probe(host)
    check_profile_device(profile, info)
    apply_plan(plan, profile, info, host, args.confirm, args.no_auto_restore)
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    plan = load_plan(args.plan)
    host = normalize_host(args.host) if args.host else plan["host"]
    info = probe(host)
    verify_plan(plan, load_profile(plan["profile"]["id"]), info, check_expiry=False)
    failures = verify_actions(host, info, plan["actions"])
    # verify is read-only and has no "before" snapshot: any disabled core package is a red flag.
    problems = core_regression(host, set())
    for failure in failures + problems:
        print(f"[FAIL] {failure}")
    print("\n设置与包状态：")
    for action in plan["actions"]:
        if action["type"] == "setting":
            actual = settings_get(host, action["namespace"], action["key"])
            print(f"  {action['namespace']}/{action['key']} = {actual!r}（期望 {action['value']!r}）")
        else:
            state = "disabled" if action["package"] in info["disabled"] else "enabled/unknown"
            print(f"  {action['package']}: {state}")
    try:
        logcat = shell(host, "logcat -b all -d", timeout=30)
        lines = [line for line in logcat.splitlines() if "BOOT_ADVERT" in line][-5:]
        print("\n开机广告日志（最近 5 条）：")
        for line in lines:
            print(f"  {line.strip()}")
        if not lines:
            print("  （未找到 BOOT_ADVERT；以重启观察为准）")
    except CliError:
        print("\n（无法读取 logcat；以重启观察为准）")
    print("\n人工验证：重启电视，观察开机过程是否还有广告。")
    print("自动化检查不能替代人工观察；getprop 单独一条不能作为成功证据。")
    if failures or problems:
        raise CliError(EXIT_PARTIAL, "验证未通过。")
    return EXIT_OK


def cmd_restore(args: argparse.Namespace) -> int:
    require_owner(args)
    if args.force_device_mismatch and not args.i_accept_device_mismatch:
        raise CliError(
            EXIT_USAGE,
            "使用 --force-device-mismatch 时必须再加 --i-accept-device-mismatch，"
            "表示你确认要把备份还原到另一台/不匹配的电视。",
        )
    host = normalize_host(args.host)
    backup_path = Path(args.backup).expanduser().resolve()
    backup_root = backups_dir().resolve()
    if backup_root not in backup_path.parents and not args.allow_external_backup:
        raise CliError(
            EXIT_USAGE,
            f"备份不在默认目录 {backup_root} 下。如确需使用外部文件，请加 --allow-external-backup。",
        )
    info = probe(host, require_serial=False)
    lock = acquire_lock(info)
    try:
        restore_from_backup(host, backup_path, args.dry_run, args.force_device_mismatch)
    finally:
        release_lock(lock)
    if args.dry_run:
        print("\n--dry-run：未做任何修改。")
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    info = probe(normalize_host(args.host))
    masked_ip = ".".join(info["host"].split(":")[0].split(".")[:-1] + ["x"])
    print("# tv-ads-close 设备报告（脱敏）\n")
    print(f"- 品牌/型号：{info['brand']} {info['model']}")
    print(f"- 代号：{info['device']}")
    print(f"- Android：{info['android']}（SDK {info['sdk']}）")
    print(f"- 固件：{info['build']}")
    print(f"- 序列号：***{info['serial_tail']}")
    print(f"- IP：{masked_ip}")
    print(f"- 已安装包：{len(info['packages'])}；已停用：{len(info['disabled'])}")
    print("\n广告相关包状态：")
    for pkg in sorted(ALLOWED_PACKAGES):
        state = "未安装"
        if pkg in info["packages"]:
            state = "已停用" if pkg in info["disabled"] else "启用"
        print(f"- {pkg}：{state}")
    print("\n未覆盖：首页推荐流、App 内广告、会员广告。")
    print("\n提交 issue 前请确认已删除个人信息（IP 已自动脱敏）。")
    return EXIT_OK


def normalize_host(host: str) -> str:
    host = host.strip()
    if not host:
        raise CliError(EXIT_USAGE, "缺少 --host")
    return host if ":" in host else f"{host}:5555"


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tv-ads-close",
        description="Safely disable system ads on Xiaomi/Redmi TVs over ADB (plan-first, reversible).",
    )
    parser.add_argument("--version", action="version", version=f"tv-ads-close {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="show a plan with fake data (no device)")
    demo.set_defaults(func=cmd_demo)

    doctor = sub.add_parser("doctor", help="check python/adb/backup dir/profiles")
    doctor.set_defaults(func=cmd_doctor)

    probe_parser = sub.add_parser("probe", help="read-only device probe")
    probe_parser.add_argument("--host", required=True)
    probe_parser.add_argument("--json", action="store_true")
    probe_parser.set_defaults(func=cmd_probe)

    plan = sub.add_parser("plan", help="build a plan artifact (read-only)")
    plan.add_argument("--host", required=True)
    plan.add_argument("--profile", default="auto")
    plan.add_argument("--include-observed", action="store_true", help="allow E1 (single-device observed) actions")
    plan.add_argument("--include-risky", action="store_true", help="allow medium/opt-in actions")
    plan.add_argument("--save", nargs="?", const="__DEFAULT__", default=None, help="plan output path")
    plan.add_argument("--json", action="store_true")
    plan.add_argument("--attest-owner", action="store_true")
    plan.set_defaults(func=cmd_plan)

    apply_parser = sub.add_parser("apply", help="apply a saved plan (writes + backup)")
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--confirm", required=True, help="8-hex confirm code printed by plan")
    apply_parser.add_argument("--host", default=None)
    apply_parser.add_argument("--attest-owner", action="store_true")
    apply_parser.add_argument("--no-auto-restore", action="store_true")
    apply_parser.set_defaults(func=cmd_apply)

    verify_parser = sub.add_parser("verify", help="read-only verification of a plan")
    verify_parser.add_argument("--plan", required=True)
    verify_parser.add_argument("--host", default=None)
    verify_parser.set_defaults(func=cmd_verify)

    restore = sub.add_parser("restore", help="restore from a backup (writes)")
    restore.add_argument("--host", required=True)
    restore.add_argument("--backup", required=True)
    restore.add_argument("--attest-owner", action="store_true")
    restore.add_argument("--dry-run", action="store_true")
    restore.add_argument("--force-device-mismatch", action="store_true")
    restore.add_argument("--i-accept-device-mismatch", action="store_true")
    restore.add_argument("--allow-external-backup", action="store_true")
    restore.set_defaults(func=cmd_restore)

    report = sub.add_parser("report", help="print a redacted device report")
    report.add_argument("--host", required=True)
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CliError as exc:
        print(f"错误[{exc.code}]：{exc.message}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("\n已取消。如已开始写入，请按备份路径执行 restore。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
