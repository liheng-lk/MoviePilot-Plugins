from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
ENTRY_API = (PLUGIN / "guangya_api_v112.py").read_text(encoding="utf-8")
COMPAT = (PLUGIN / "host_compat.py").read_text(encoding="utf-8")


def test_host_compat_installs_before_legacy_app_log_import():
    compat_import = ENTRY_API.index("from .host_compat import install_host_compat")
    compat_call = ENTRY_API.index("install_host_compat()", compat_import)
    legacy_import = ENTRY_API.index("from app.log import logger")
    assert compat_import < compat_call < legacy_import


def test_host_compat_bridges_removed_v3_modules_to_stable_sdk():
    assert 'sys.modules.setdefault("app.log", log_module)' in COMPAT
    assert "from app.sdk.logging import logger" in COMPAT
    assert 'sys.modules.setdefault("app.helper.storage", storage_module)' in COMPAT
    assert "from app.sdk.services import StorageHelper" in COMPAT
