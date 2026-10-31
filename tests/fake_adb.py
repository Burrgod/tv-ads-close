#!/usr/bin/env python3
"""Deterministic fake `adb` used by tests. State lives in TV_FAKE_STATE/state.json."""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

STATE_DIR = Path(os.environ["TV_FAKE_STATE"])
STATE_FILE = STATE_DIR / "state.json"

CORE = [
    "com.mitv.tvhome",
    "com.xiaomi.mitv.settings",
    "com.xiaomi.mitv.tvplayer",
    "com.xiaomi.mitv.tvmanager",
    "com.xiaomi.voicecontrol",
    "com.xiaomi.miplay",
    "com.xiaomi.mitv.smartshare",
    "com.sohu.inputmethod.sogou.tv",
    "com.xiaomi.account",
    "com.xiaomi.mitv.appstore",
    "com.xiaomi.mitv.upgrade",
    "com.android.systemui",
    "com.android.settings",
    "com.android.bluetooth",
    "com.android.packageinstaller",
]
EXTRA = ["com.android.permissioncontroller", "com.android.launcher3", "com.miui.home", "com.mitv.care"]
TARGETS = [
    "com.miui.analytics",
    "com.miui.tv.analytics",
    "com.xiaomi.statistic",
    "com.xiaomi.tvqs",
    "com.xiaomi.mitv.tvpush.tvpushservice",
    "com.mitv.shoplugin",
    "com.mitv.cloudcontrol",
    "com.duokan.videodaily",
]


def defaults() -> dict:
    return {
        "host": "",
        "device_state": "device",
        "model": "MiTV-MFZP0",
        "brand": "xiaomi",
        "device": "walle",
        "android": "9",
        "sdk": "28",
        "build": "25.5.22.2496",
        "serial": "ABC123456789",
        "serial_boot": "",
        "settings": {"global:mitv.settings.advertise.state": "0"},
        "packages": CORE + EXTRA + TARGETS,
        "disabled": ["com.mitv.care"],
        "shell_calls": 0,
    }


def load() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state = defaults()
    save(state)
    return state


def save(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fail_if_matched(command: str) -> None:
    needle = os.environ.get("TV_FAKE_FAIL_SUBSTR")
    if needle and needle in command:
        print(f"error: injected failure for {command}", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    args = sys.argv[1:]
    state = load()
    if not args:
        print("fake adb: missing command", file=sys.stderr)
        return 1
    if args == ["version"]:
        print("Android Debug Bridge version 1.0.41")
        print("Version 35.0.0-11583719")
        return 0
    if args[0] == "connect":
        state["host"] = args[1]
        save(state)
        print(f"connected to {args[1]}")
        return 0
    if args[0] == "devices":
        print("List of devices attached")
        host = state.get("host", "")
        if host:
            print(f"{host}\t{state.get('device_state', 'device')}")
        print("")
        return 0
    if args[0] == "-s" and len(args) >= 4 and args[2] == "shell":
        command = args[3]
        state["shell_calls"] = int(state.get("shell_calls", 0)) + 1
        save(state)
        fail_if_matched(command)
        return handle_shell(state, command)
    print(f"fake adb: unsupported args {args}", file=sys.stderr)
    return 1


def handle_shell(state: dict, command: str) -> int:
    upper = command.strip()
    if upper.startswith("getprop "):
        prop = shlex.split(upper)[1]
        mapping = {
            "ro.product.model": state["model"],
            "ro.product.brand": state["brand"],
            "ro.product.device": state["device"],
            "ro.build.version.release": state["android"],
            "ro.build.version.sdk": state["sdk"],
            "ro.build.display.id": state["build"],
            "ro.serialno": state["serial"],
            "ro.boot.serialno": state.get("serial_boot") or state["serial"],
        }
        print(mapping.get(prop, ""))
        return 0
    if upper.startswith("settings get "):
        parts = shlex.split(upper)
        if len(parts) != 4:
            print("fake adb: bad settings get", file=sys.stderr)
            return 1
        key = f"{parts[2]}:{parts[3]}"
        print(state["settings"].get(key, "null"))
        return 0
    if upper.startswith("settings put "):
        parts = shlex.split(upper)
        if len(parts) != 5:
            print("fake adb: bad settings put", file=sys.stderr)
            return 1
        state["settings"][f"{parts[2]}:{parts[3]}"] = parts[4]
        save(state)
        return 0
    if upper.startswith("settings delete "):
        parts = shlex.split(upper)
        if len(parts) != 4:
            print("fake adb: bad settings delete", file=sys.stderr)
            return 1
        state["settings"].pop(f"{parts[2]}:{parts[3]}", None)
        save(state)
        return 0
    if upper.startswith("pm list packages"):
        if os.environ.get("TV_FAKE_LIST_FAIL"):
            print("Error: package manager unavailable", file=sys.stderr)
            return 1
        disabled = upper.endswith(" -d")
        packages = state["disabled"] if disabled else state["packages"]
        for pkg in sorted(packages):
            print(f"package:{pkg}")
        return 0
    if upper.startswith("pm disable-user --user 0 "):
        pkg = shlex.split(upper)[-1]
        if pkg not in state["packages"]:
            print(f"Error: package {pkg} not found", file=sys.stderr)
            return 1
        if pkg not in state["disabled"]:
            state["disabled"].append(pkg)
            save(state)
        print(f"Package {pkg} new state: disabled-user")
        return 0
    if upper.startswith("pm enable --user 0 "):
        pkg = shlex.split(upper)[-1]
        if pkg not in state["packages"]:
            print(f"Error: package {pkg} not found", file=sys.stderr)
            return 1
        if pkg in state["disabled"]:
            state["disabled"].remove(pkg)
            save(state)
        print(f"Package {pkg} new state: enabled")
        return 0
    if upper.startswith("logcat"):
        print("01-01 00:00:00.000 I/BOOT_ADVERT: BOOT_ADVERT_KEY playing is : 0")
        print("01-01 00:00:00.000 I/ActivityManager: boot completed")
        return 0
    print(f"fake adb: unsupported shell command: {command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
