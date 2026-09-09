from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GuangYaV11220Preflight(unittest.TestCase):
    def test_guangya_v3_contract_suite(self):
        result = subprocess.run(
            [sys.executable, "tests/v3/guangyatransferassistant/run_contract_tests.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            self.fail(
                "GuangYaTransferAssistant contract suite failed before unrelated repository contracts:\n"
                + result.stdout[-20000:]
                + "\n"
                + result.stderr[-5000:]
            )


if __name__ == "__main__":
    unittest.main()
