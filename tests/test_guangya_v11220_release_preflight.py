from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GuangYaV11220ReleasePreflight(unittest.TestCase):
    def test_final_v11220_guangya_contract_suite(self):
        result = subprocess.run(
            [sys.executable, "tests/v3/guangyatransferassistant/run_contract_tests.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            self.fail(
                "Final v1.12.20 GuangYaTransferAssistant contract suite failed:\n"
                + result.stdout[-30000:]
                + "\n"
                + result.stderr[-5000:]
            )


if __name__ == "__main__":
    unittest.main()
