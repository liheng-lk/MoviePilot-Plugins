from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v196_uses_current_moviepilot_subscribe_contract():
    assert "from app.chain.subscribe import SubscribeChain" in LEGACY
    assert "from app.application.subscription.contract import build_subscribe_meta" in LEGACY
    assert "from app.chain.subscribe import SubscribeChain, build_subscribe_meta" not in LEGACY


def test_v196_keeps_early_v3_fallback():
    assert "except ImportError" in LEGACY
    assert "from app.chain.subscribe import build_subscribe_meta" in LEGACY


def test_v196_release_marker():
    assert 'plugin_version = "1.12.15"' in ENTRY
    assert 'build_id = "20260905-r61"' in ENTRY
