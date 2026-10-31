import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tv_ads_close as tc  # noqa: E402


class ProfileValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = copy.deepcopy(tc.load_profile("xiaomi-mitv-mfzp0"))
        tc.validate_profile(self.profile)

    def test_profile_is_valid(self) -> None:
        self.assertEqual(self.profile["status"], "observed")
        self.assertEqual(self.profile["schema_version"], 2)

    def test_rejects_core_package(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        unsafe["disable"].append(
            {
                "package": "com.mitv.tvhome",
                "reason": "test",
                "risk": "low",
                "evidence": {"level": "E1", "method": "test", "date": "2026-10-30"},
            }
        )
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)

    def test_rejects_package_outside_allowlist(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        unsafe["disable"].append(
            {
                "package": "com.android.launcher3",
                "reason": "test",
                "risk": "low",
                "evidence": {"level": "E1", "method": "test", "date": "2026-10-30"},
            }
        )
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)

    def test_rejects_critical_setting_key(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        unsafe["settings"]["global"]["adb_enabled"] = {
            "value": "0",
            "reason": "test",
            "risk": "low",
            "evidence": {"level": "E1", "method": "test", "date": "2026-10-30"},
        }
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)

    def test_rejects_empty_firmware(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        unsafe["firmware"] = []
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)

    def test_rejects_wildcard_firmware(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        unsafe["firmware"] = ["*"]
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)

    def test_rejects_medium_without_opt_in(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        for item in unsafe["disable"]:
            if item["package"] == "com.xiaomi.mitv.tvpush.tvpushservice":
                item["opt_in"] = False
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)

    def test_rejects_verified_with_e1_evidence(self) -> None:
        unsafe = copy.deepcopy(self.profile)
        unsafe["status"] = "verified"
        with self.assertRaises(tc.CliError):
            tc.validate_profile(unsafe)


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = tc.load_profile("xiaomi-mitv-mfzp0")

    def test_observed_profile_has_no_default_actions(self) -> None:
        actions = tc.select_actions(self.profile, include_observed=False, include_risky=False)
        self.assertEqual(actions, [])

    def test_observed_profile_includes_low_risk_actions(self) -> None:
        actions = tc.select_actions(self.profile, include_observed=True, include_risky=False)
        packages = {a["package"] for a in actions if a["type"] == "disable"}
        self.assertIn("com.miui.analytics", packages)
        self.assertNotIn("com.xiaomi.mitv.tvpush.tvpushservice", packages)
        self.assertEqual(len(actions), 7)  # 1 setting + 6 low-risk packages

    def test_risky_actions_require_flag(self) -> None:
        actions = tc.select_actions(self.profile, include_observed=True, include_risky=True)
        packages = {a["package"] for a in actions if a["type"] == "disable"}
        self.assertIn("com.xiaomi.mitv.tvpush.tvpushservice", packages)
        self.assertIn("com.mitv.cloudcontrol", packages)
        self.assertEqual(len(actions), 9)

    def test_plan_requires_actions(self) -> None:
        info = {
            "host": "demo",
            "model": "MiTV-MFZP0",
            "brand": "xiaomi",
            "device": "walle",
            "android": "9",
            "sdk": "28",
            "build": "25.5.22.2496",
            "serial_hash": "a" * 64,
            "serial_tail": "6789",
            "packages": set(),
            "disabled": set(),
        }
        with self.assertRaises(tc.CliError):
            tc.build_plan(self.profile, info, [], False, False)


if __name__ == "__main__":
    unittest.main()
