from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tv_ads_close as tc  # noqa: E402


class FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="tvac-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.state_dir = self.tmp / "state"
        self.bin = self.tmp / "bin"
        self.bin.mkdir(parents=True)
        wrapper = self.bin / "adb"
        fake = ROOT / "tests" / "fake_adb.py"
        wrapper.write_text(
            "#!/bin/sh\nexec " + json.dumps(sys.executable) + " " + json.dumps(str(fake)) + ' "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        self.env = {
            "TV_ADS_CLOSE_HOME": str(self.home),
            "TV_FAKE_STATE": str(self.state_dir),
            "ADB": str(wrapper),
        }
        patcher = mock.patch.dict(os.environ, self.env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: os.environ.pop("TV_FAKE_FAIL_SUBSTR", None))
        self.addCleanup(lambda: os.environ.pop("TV_FAKE_LIST_FAIL", None))

    # -- helpers ---------------------------------------------------------
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tc.main(args)
        return code, out.getvalue(), err.getvalue()

    def fake_state(self) -> dict:
        return json.loads((self.state_dir / "state.json").read_text(encoding="utf-8"))

    def write_fake_state(self, state: dict) -> None:
        (self.state_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def make_plan(self, flags: list[str] | None = None) -> tuple[Path, dict]:
        save = self.tmp / "plan.json"
        args = [
            "plan",
            "--host",
            "127.0.0.1",
            "--attest-owner",
            "--save",
            str(save),
        ]
        args.extend(flags or ["--include-observed", "--include-risky"])
        code, out, err = self.run_cli(args)
        self.assertEqual(code, 0, msg=out + err)
        return save, json.loads(save.read_text(encoding="utf-8"))

    def apply(self, plan_path: Path, confirm: str | None = None) -> tuple[int, str, str]:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        return self.run_cli(
            [
                "apply",
                "--plan",
                str(plan_path),
                "--confirm",
                confirm or plan["confirm_code"],
                "--attest-owner",
            ]
        )

    def disable_all(self) -> tuple[Path, dict]:
        plan_path, plan = self.make_plan()
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 0, msg=out + err)
        return plan_path, plan

    def latest_backup(self) -> Path:
        backups = sorted((self.home / "backups").glob("*.json"))
        self.assertTrue(backups, "no backup written")
        return [p for p in backups if ".journal." not in p.name][-1]

    def resign(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("signature", None)
        raw = tc.sign_backup(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")

    def resign_plan(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("plan_signature", None)
        raw = tc.sign_plan(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")

    # -- tests -----------------------------------------------------------
    def test_plan_and_apply_success(self) -> None:
        plan_path, plan = self.make_plan()
        self.assertEqual(len(plan["actions"]), 9)
        self.assertEqual(plan["profile"]["status"], "observed")
        self.assertIn("E1", plan["warnings"][1])
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        self.assertEqual(state["settings"]["global:mitv.settings.advertise.state"], "1")
        for target in (
            "com.miui.analytics",
            "com.miui.tv.analytics",
            "com.xiaomi.statistic",
            "com.xiaomi.tvqs",
            "com.xiaomi.mitv.tvpush.tvpushservice",
            "com.mitv.shoplugin",
            "com.mitv.cloudcontrol",
            "com.duokan.videodaily",
        ):
            self.assertIn(target, state["disabled"])
        self.assertTrue(self.latest_backup().exists())
        self.assertTrue(list((self.home / "backups").glob("baseline-*.json")))
        journals = list((self.home / "backups").glob("*.journal.json"))
        self.assertEqual(len(journals), 1)
        journal = json.loads(journals[0].read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "applied")
        code, out, err = self.run_cli(["verify", "--plan", str(plan_path)])
        self.assertEqual(code, 0, msg=out + err)
        code, out, err = self.run_cli(["report", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        self.assertNotIn("ABC123456789", out)
        self.assertIn("127.0.0.x", out)

    def test_plan_without_observed_flag_refused(self) -> None:
        save = self.tmp / "plan.json"
        code, out, err = self.run_cli(
            ["plan", "--host", "127.0.0.1", "--attest-owner", "--save", str(save)]
        )
        self.assertEqual(code, 2, msg=out + err)
        self.assertFalse(save.exists())

    def test_apply_rejects_wrong_confirm_code(self) -> None:
        plan_path, _ = self.make_plan()
        code, out, err = self.apply(plan_path, confirm="00000000")
        self.assertEqual(code, 2, msg=out + err)
        self.assertEqual(self.fake_state()["settings"]["global:mitv.settings.advertise.state"], "0")

    def test_apply_rejects_tampered_plan(self) -> None:
        plan_path, plan = self.make_plan()
        plan["actions"][0]["value"] = "0"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)
        self.assertEqual(self.fake_state()["settings"]["global:mitv.settings.advertise.state"], "0")

    def test_apply_rejects_expired_plan(self) -> None:
        plan_path, plan = self.make_plan()
        plan["expires_at"] = "2000-01-01T00:00:00+00:00"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)

    def test_apply_rejects_device_mismatch(self) -> None:
        plan_path, _ = self.make_plan()
        state = self.fake_state()
        state["serial"] = "ZZZ999999999"
        self.write_fake_state(state)
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 7, msg=out + err)

    def test_failure_stops_and_auto_restores(self) -> None:
        os.environ["TV_FAKE_FAIL_SUBSTR"] = "com.miui.analytics"
        plan_path, _ = self.make_plan()
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 6, msg=out + err)
        state = self.fake_state()
        self.assertEqual(state["settings"]["global:mitv.settings.advertise.state"], "0")
        self.assertEqual(state["disabled"], ["com.mitv.care"])
        journal = json.loads(list((self.home / "backups").glob("*.journal.json"))[0].read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "failed")

    def test_list_packages_failure_is_hard_error(self) -> None:
        os.environ["TV_FAKE_LIST_FAIL"] = "1"
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 6, msg=out + err)
        self.assertIn("pm list packages", err)

    def test_restore_wrong_device_rejected_then_forced(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        raw = json.loads(backup.read_text(encoding="utf-8"))
        raw["device"]["serial_hash"] = "f" * 64
        backup.write_text(json.dumps(raw), encoding="utf-8")
        self.resign(backup)
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 7, msg=out + err)
        code, out, err = self.run_cli(
            [
                "restore",
                "--host",
                "127.0.0.1",
                "--backup",
                str(backup),
                "--attest-owner",
                "--force-device-mismatch",
                "--i-accept-device-mismatch",
            ]
        )
        self.assertEqual(code, 0, msg=out + err)
        self.assertEqual(self.fake_state()["disabled"], ["com.mitv.care"])

    def test_restore_dry_run_then_real(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner", "--dry-run"]
        )
        self.assertEqual(code, 0, msg=out + err)
        self.assertIn("com.miui.analytics", self.fake_state()["disabled"])
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 0, msg=out + err)
        self.assertEqual(self.fake_state()["disabled"], ["com.mitv.care"])
        self.assertEqual(self.fake_state()["settings"]["global:mitv.settings.advertise.state"], "0")

    def test_restore_failure_exits_nonzero(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        os.environ["TV_FAKE_FAIL_SUBSTR"] = "pm enable"
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 6, msg=out + err)

    def test_demo_writes_nothing(self) -> None:
        code, out, err = self.run_cli(["demo"])
        self.assertEqual(code, 0, msg=out + err)
        self.assertFalse(self.home.exists())
        self.assertFalse(self.state_dir.exists())

    def test_probe_allows_no_disabled_packages(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["disabled"] = []
        self.write_fake_state(state)
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)

    def test_doctor(self) -> None:
        code, out, err = self.run_cli(["doctor"])
        self.assertEqual(code, 0, msg=out + err)
        self.assertIn("profiles：1/1", out)

    def test_explicit_profile_checks_all_device_fields(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["model"] = "OtherTV"
        self.write_fake_state(state)
        code, out, err = self.run_cli(
            [
                "plan",
                "--host",
                "127.0.0.1",
                "--profile",
                "xiaomi-mitv-mfzp0",
                "--include-observed",
                "--attest-owner",
                "--save",
                str(self.tmp / "plan.json"),
            ]
        )
        self.assertEqual(code, 7, msg=out + err)

    def test_explicit_profile_rejects_unverified_firmware(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["build"] = "0.0.0.0"
        self.write_fake_state(state)
        code, out, err = self.run_cli(
            [
                "plan",
                "--host",
                "127.0.0.1",
                "--profile",
                "xiaomi-mitv-mfzp0",
                "--include-observed",
                "--attest-owner",
                "--save",
                str(self.tmp / "plan.json"),
            ]
        )
        self.assertEqual(code, 5, msg=out + err)

    def test_verify_detects_disabled_core_package(self) -> None:
        plan_path, _ = self.make_plan()
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["disabled"].append("com.mitv.tvhome")
        self.write_fake_state(state)
        code, out, err = self.run_cli(["verify", "--plan", str(plan_path)])
        self.assertEqual(code, 6, msg=out + err)

    def test_apply_rejects_action_outside_allowlist_even_with_valid_integrity(self) -> None:
        plan_path, plan = self.make_plan()
        plan["actions"].append(
            {"type": "disable", "package": "com.android.launcher3", "reason": "x", "risk": "low", "opt_in": False, "evidence": "E1"}
        )
        plan["action_hash"] = tc.canonical_actions(plan["actions"])
        plan["integrity"] = tc.plan_integrity(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.resign_plan(plan_path)
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)
        self.assertEqual(self.fake_state()["settings"]["global:mitv.settings.advertise.state"], "0")

    def test_apply_rejects_flags_tamper_without_signature(self) -> None:
        plan_path, plan = self.make_plan(flags=["--include-observed"])
        plan["flags"]["include_risky"] = True
        plan["actions"] = tc.select_actions(
            tc.load_profile("xiaomi-mitv-mfzp0"), include_observed=True, include_risky=True
        )
        plan["action_hash"] = tc.canonical_actions(plan["actions"])
        plan["integrity"] = tc.plan_integrity(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)
        self.assertNotIn("com.xiaomi.mitv.tvpush.tvpushservice", self.fake_state()["disabled"])

    def test_apply_rejects_expired_plan_after_resigning(self) -> None:
        plan_path, plan = self.make_plan()
        plan["expires_at"] = "2000-01-01T00:00:00+00:00"
        plan["integrity"] = tc.plan_integrity(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.resign_plan(plan_path)
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)

    def test_apply_rejects_plan_device_mismatch_after_resigning(self) -> None:
        plan_path, plan = self.make_plan()
        plan["device"]["serial_hash"] = "f" * 64
        plan["integrity"] = tc.plan_integrity(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.resign_plan(plan_path)
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 7, msg=out + err)

    def test_probe_falls_back_to_boot_serial(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["serial"] = "unknown"
        state["serial_boot"] = "BOOT123456"
        self.write_fake_state(state)
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        self.assertIn("***3456", out)

    def test_verify_ignores_plan_expiry(self) -> None:
        plan_path, plan = self.make_plan()
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 0, msg=out + err)
        plan["expires_at"] = "2000-01-01T00:00:00+00:00"
        plan["integrity"] = tc.plan_integrity(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.resign_plan(plan_path)
        code, out, err = self.run_cli(["verify", "--plan", str(plan_path)])
        self.assertEqual(code, 0, msg=out + err)

    def test_backup_non_dict_rejected_without_traceback(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        backup.write_text("[]", encoding="utf-8")
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 2, msg=out + err)

    def test_malformed_backup_rejected_without_traceback(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        raw = json.loads(backup.read_text(encoding="utf-8"))
        raw["packages"] = ["not-a-dict"]
        backup.write_text(json.dumps(raw), encoding="utf-8")
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 2, msg=out + err)

    def test_plan_with_non_dict_actions_rejected(self) -> None:
        plan_path, plan = self.make_plan()
        plan["actions"] = ["not-a-dict"]
        plan["integrity"] = tc.plan_integrity(plan)
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.resign_plan(plan_path)
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)

    def test_malformed_plan_rejected_without_traceback(self) -> None:
        plan_path, plan = self.make_plan()
        del plan["actions"]
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 9, msg=out + err)

    def test_plan_and_apply_require_owner_attestation(self) -> None:
        code, out, err = self.run_cli(
            ["plan", "--host", "127.0.0.1", "--include-observed", "--save", str(self.tmp / "p.json")]
        )
        self.assertEqual(code, 2, msg=out + err)
        plan_path, plan = self.make_plan()
        code, out, err = self.run_cli(
            ["apply", "--plan", str(plan_path), "--confirm", plan["confirm_code"]]
        )
        self.assertEqual(code, 2, msg=out + err)

    def test_probe_unauthorized(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["device_state"] = "unauthorized"
        self.write_fake_state(state)
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 3, msg=out + err)

    def test_probe_requires_serial(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["serial"] = ""
        self.write_fake_state(state)
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 6, msg=out + err)

    def test_restore_rejects_tampered_setting_key(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        raw = json.loads(backup.read_text(encoding="utf-8"))
        del raw["settings"]["global"]["mitv.settings.advertise.state"]
        raw["settings"]["global"]["adb_enabled"] = {"present": True, "value": "0"}
        backup.write_text(json.dumps(raw), encoding="utf-8")
        self.resign(backup)
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 2, msg=out + err)

    def test_restore_rejects_modified_signature(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        raw = json.loads(backup.read_text(encoding="utf-8"))
        raw["device"]["model"] = "OtherTV"
        backup.write_text(json.dumps(raw), encoding="utf-8")
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 2, msg=out + err)

    def test_auto_restore_preserves_non_standard_original_value(self) -> None:
        code, out, err = self.run_cli(["probe", "--host", "127.0.0.1"])
        self.assertEqual(code, 0, msg=out + err)
        state = self.fake_state()
        state["settings"]["global:mitv.settings.advertise.state"] = "2"
        self.write_fake_state(state)
        os.environ["TV_FAKE_FAIL_SUBSTR"] = "com.miui.analytics"
        plan_path, _ = self.make_plan()
        code, out, err = self.apply(plan_path)
        self.assertEqual(code, 6, msg=out + err)
        self.assertEqual(self.fake_state()["settings"]["global:mitv.settings.advertise.state"], "2")

    def test_verify_stage_failure_triggers_auto_restore(self) -> None:
        plan_path, _ = self.make_plan()
        original = tc.verify_actions

        def boom(*args, **kwargs):
            raise tc.CliError(tc.EXIT_PARTIAL, "injected verify failure")

        tc.verify_actions = boom
        try:
            code, out, err = self.apply(plan_path)
        finally:
            tc.verify_actions = original
        self.assertEqual(code, 6, msg=out + err)
        self.assertEqual(self.fake_state()["settings"]["global:mitv.settings.advertise.state"], "0")
        self.assertEqual(self.fake_state()["disabled"], ["com.mitv.care"])

    def test_backup_key_is_private_and_required(self) -> None:
        self.disable_all()
        key = self.home / "backup.key"
        self.assertTrue(key.exists())
        self.assertEqual(key.stat().st_mode & 0o077, 0)
        backup = self.latest_backup()
        key.unlink()
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 8, msg=out + err)

    def test_doctor_mentions_keys(self) -> None:
        code, out, err = self.run_cli(["doctor"])
        self.assertEqual(code, 0, msg=out + err)
        self.assertIn("备份签名", out)
        self.assertIn("计划签名", out)

    def test_restore_respects_lock(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        plan = json.loads((self.tmp / "plan.json").read_text(encoding="utf-8"))
        locks = self.home / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / (plan["device"]["serial_hash"][:16] + ".lock")).write_text("other", encoding="utf-8")
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 6, msg=out + err)

    def test_restore_with_unreadable_serial_requires_force(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        state = self.fake_state()
        state["serial"] = ""
        state["serial_boot"] = ""
        self.write_fake_state(state)
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(backup), "--attest-owner"]
        )
        self.assertEqual(code, 7, msg=out + err)
        code, out, err = self.run_cli(
            [
                "restore",
                "--host",
                "127.0.0.1",
                "--backup",
                str(backup),
                "--attest-owner",
                "--force-device-mismatch",
                "--i-accept-device-mismatch",
            ]
        )
        self.assertEqual(code, 0, msg=out + err)
        self.assertEqual(self.fake_state()["disabled"], ["com.mitv.care"])

    def test_force_device_mismatch_needs_second_flag(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        raw = json.loads(backup.read_text(encoding="utf-8"))
        raw["device"]["serial_hash"] = "f" * 64
        backup.write_text(json.dumps(raw), encoding="utf-8")
        self.resign(backup)
        code, out, err = self.run_cli(
            [
                "restore",
                "--host",
                "127.0.0.1",
                "--backup",
                str(backup),
                "--attest-owner",
                "--force-device-mismatch",
            ]
        )
        self.assertEqual(code, 2, msg=out + err)

    def test_scan_is_gone_and_allow_untested_is_gone(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli(["scan"])
        with self.assertRaises(SystemExit):
            self.run_cli(["apply", "--plan", "x", "--confirm", "x", "--allow-untested"])

    def test_external_backup_requires_flag(self) -> None:
        self.disable_all()
        backup = self.latest_backup()
        external = self.tmp / "outside.json"
        shutil.copy(backup, external)
        code, out, err = self.run_cli(
            ["restore", "--host", "127.0.0.1", "--backup", str(external), "--attest-owner"]
        )
        self.assertEqual(code, 2, msg=out + err)
        self.assertIn("--allow-external-backup", err)


if __name__ == "__main__":
    unittest.main()
