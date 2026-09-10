from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
SURVIVAL = PLUGIN / "organizer_runtime_survival_v382.py"
EXECUTION = PLUGIN / "organizer_execution_v360.py"


class RuntimeSurvivalV382ContractTest(unittest.TestCase):
    def test_sources_parse(self):
        ast.parse(SURVIVAL.read_text(encoding="utf-8"))
        ast.parse(EXECUTION.read_text(encoding="utf-8"))

    def test_survival_installs_after_final_v380_policy(self):
        source = EXECUTION.read_text(encoding="utf-8")
        self.assertLess(
            source.index("install_watch_policy_v380()"),
            source.index("install_runtime_survival_v382()"),
        )
        self.assertIn("_v382_runtime_survival_patch_ready", source)

    def test_tick_catches_all_runtime_errors_and_never_reraises(self):
        source = SURVIVAL.read_text(encoding="utf-8")
        block = source.split("    def guarded_tick", 1)[1].split("    def status", 1)[0]
        self.assertIn("except Exception as err", block)
        self.assertIn("return", block)
        self.assertNotIn("raise\n", block)
        self.assertIn("_FAILURE_LIMIT = 3", source)
        self.assertIn("_COOLDOWN_SECONDS = 300.0", source)

    def test_boot_grace_suppresses_only_automatic_full_due(self):
        source = SURVIVAL.read_text(encoding="utf-8")
        self.assertIn("_BOOT_GRACE_SECONDS = 180.0", source)
        full_due = source.split("    def full_due", 1)[1].split("    def guarded_tick", 1)[0]
        self.assertIn("_v382_boot_grace_active", full_due)
        self.assertIn("return False", full_due)
        self.assertIn("return bool(original_full_due(self))", full_due)

    def test_status_failure_is_also_isolated(self):
        source = SURVIVAL.read_text(encoding="utf-8")
        block = source.split("    def status", 1)[1].split("    _watch._full_due", 1)[0]
        self.assertIn("except Exception as err", block)
        self.assertIn("监控状态暂不可用，插件本身仍正常", block)
        self.assertIn("runtime_survival_guard", block)


if __name__ == "__main__":
    unittest.main()
