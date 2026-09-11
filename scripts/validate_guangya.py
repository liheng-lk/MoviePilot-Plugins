from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
CONTRACT = ROOT / "tests" / "v3" / "guangyatransferassistant" / "run_contract_tests.py"


def _run(label: str, command: list[str]) -> None:
    print(f"\n==> {label}")
    print("$", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def _json_contract() -> None:
    print("\n==> JSON/version metadata")
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")

    package_version = str(package["GuangYaTransferAssistant"]["version"])
    plugin_version = str(plugin["version"])
    marker = f'plugin_version = "{package_version}"'
    if package_version != plugin_version:
        raise SystemExit(
            f"version mismatch: package.v3={package_version}, plugin.json={plugin_version}"
        )
    if marker not in entry:
        raise SystemExit(
            f"version mismatch: final plugin class does not contain {marker!r}"
        )
    print(f"OK version={package_version}")


def _cleanup_python_artifacts() -> None:
    for directory in ROOT.rglob("__pycache__"):
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
    for path in ROOT.rglob("*.pyc"):
        try:
            path.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate GuangYaTransferAssistant before commit / PR."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="also run the repository unittest suite after GuangYa contracts",
    )
    args = parser.parse_args()

    print("GuangYaTransferAssistant validation")
    print(f"root: {ROOT}")
    try:
        _run(
            "Python syntax",
            [sys.executable, "-m", "compileall", "-q", str(PLUGIN)],
        )
        _run(
            "GuangYa contract / final-plugin E2E",
            [sys.executable, str(CONTRACT)],
        )
        _json_contract()

        if args.full:
            _run(
                "Repository unit tests",
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            )

        print("\nPASS: GuangYaTransferAssistant validation complete")
        return 0
    except subprocess.CalledProcessError as err:
        print(f"\nFAIL: command exited with {err.returncode}", file=sys.stderr)
        return int(err.returncode or 1)
    finally:
        _cleanup_python_artifacts()


if __name__ == "__main__":
    raise SystemExit(main())
