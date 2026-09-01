from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v195_uses_public_plugin_manager_sdk():
    assert "from app.sdk.plugins import PluginManager" in LEGACY
    assert "from app.runtime.extensions.plugin_manager import PluginManager" not in LEGACY
    assert 'running.get("ShukGuangYaDisk")' in LEGACY
    assert 'getattr(plugin, "_client", None)' in LEGACY
    assert 'getattr(plugin, "_guangya_api", None)' in LEGACY


def test_v195_keeps_runtime_fallback_without_internal_import():
    assert 'getattr(manager, "get_plugin_attr", None)' in LEGACY
    assert 'getter("ShukGuangYaDisk", "_client")' in LEGACY
    assert 'getter("ShukGuangYaDisk", "_guangya_api")' in LEGACY


def test_v195_release_marker():
    assert 'plugin_version = "1.10.2"' in ENTRY
    assert 'build_id = "20260901-r13"' in ENTRY
