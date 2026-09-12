"""Single-runtime-file contract for GuangYaTransferAssistant."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "guangyatransferassistant"


def test_plugin_runtime_contains_only_init_py():
    runtime = sorted(
        path.relative_to(PLUGIN_DIR).as_posix()
        for path in PLUGIN_DIR.rglob("*.py")
    )
    assert runtime == ["__init__.py"], (
        "GuangYaTransferAssistant runtime must be single-file; found: "
        + ", ".join(runtime)
    )
