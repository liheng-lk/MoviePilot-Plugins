from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SURVIVAL = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_runtime_survival_v382.py"


class RuntimeSurvivalV382RuntimeShapeTest(unittest.TestCase):
    def test_guarded_tick_wraps_original_tick_in_try_except(self):
        tree = ast.parse(SURVIVAL.read_text(encoding="utf-8"))
        install = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "install_runtime_survival_v382")
        guarded = next(node for node in install.body if isinstance(node, ast.FunctionDef) and node.name == "guarded_tick")
        tries = [node for node in guarded.body if isinstance(node, ast.Try)]
        self.assertTrue(tries)
        call_names = {
            getattr(node.func, "id", "")
            for node in ast.walk(tries[0])
            if isinstance(node, ast.Call)
        }
        self.assertIn("original_tick", call_names)
        self.assertTrue(any(handler.type and isinstance(handler.type, ast.Name) and handler.type.id == "Exception" for handler in tries[0].handlers))

    def test_full_due_boot_grace_is_fail_closed(self):
        source = SURVIVAL.read_text(encoding="utf-8")
        self.assertIn('if bool(getattr(self, "_v382_boot_grace_active", False)):', source)
        self.assertIn("return False", source)
        self.assertIn("_watch._full_due = full_due", source)


if __name__ == "__main__":
    unittest.main()
