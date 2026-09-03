import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PROVIDER = (PLUGIN / "provider_reliability_v1100.py").read_text(encoding="utf-8")
XUNLEI = (PLUGIN / "xunlei_reliability_v1100.py").read_text(encoding="utf-8")
DIAGNOSTICS = (PLUGIN / "diagnostics_v1100.py").read_text(encoding="utf-8")
CONSOLE = (PLUGIN / "console_ui_v1100.py").read_text(encoding="utf-8")
CONFIG = (PLUGIN / "config_ui_v1100.py").read_text(encoding="utf-8")

def test_v1100_files_parse_and_publish_current_release():
    for path in (PLUGIN / "provider_reliability_v1100.py", PLUGIN / "xunlei_reliability_v1100.py", PLUGIN / "diagnostics_v1100.py", PLUGIN / "console_ui_v1100.py", PLUGIN / "config_ui_v1100.py", PLUGIN / "__init__.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.11.0"
    assert 'plugin_version = "1.11.0"' in ENTRY
    assert 'build_id = "20260903-r41"' in ENTRY

def test_v1100_mro_installs_final_layers_before_old_layers():
    start = ENTRY.index("class GuangYaTransferAssistant")
    for token in ("GuangYaConfigUiV1100Mixin,", "GuangYaConsoleUiV1100Mixin,", "GuangYaDiagnosticsV1100Mixin,", "GuangYaProviderReliabilityV1100Mixin,", "GuangYaXunleiReliabilityV1100Mixin,"):
        assert token in ENTRY[start:]
    assert ENTRY.index("GuangYaConfigUiV1100Mixin,", start) < ENTRY.index("GuangYaConfigUiMixin,", start)
    assert ENTRY.index("GuangYaConsoleUiV1100Mixin,", start) < ENTRY.index("GuangYaStatusHardeningMixin,", start)
    assert ENTRY.index("GuangYaProviderReliabilityV1100Mixin,", start) < ENTRY.index("GuangYaProviderSourcesMixin,", start)
    assert ENTRY.index("GuangYaXunleiReliabilityV1100Mixin,", start) < ENTRY.index("GuangYaXunleiFlashMixin,", start)

def test_unified_search_exposes_xunlei_and_adaptive_magnet_queries():
    for token in ('"q"', '"kw"', '"keyword"', '"search"', "_search_viewing_xunlei", '"xunlei"', '"/providers/search/selected"'):
        assert token in PROVIDER
    assert 'headers["Authorization"] = f"Bearer {raw}"' in PROVIDER
    assert 'headers["X-API-Key"] = raw' in PROVIDER
    assert "api_provider_test" in PROVIDER and "_search_api_provider(item, keyword)" in PROVIDER

def test_xunlei_sampling_is_streamed_and_bounded():
    assert "stream=True" in XUNLEI
    assert "iter_content" in XUNLEI
    assert "_CID_SAMPLE_SIZE = 20 * 1024" in XUNLEI
    assert "if start != 0:" in XUNLEI
    assert "response.close()" in XUNLEI
    assert "response.content" not in XUNLEI
    assert '"/xunlei/flash/preflight"' in XUNLEI
    assert "_get_guangya_runtime" in XUNLEI

def test_full_diagnostics_is_non_destructive_and_exposed_on_console():
    assert '"/diagnostics/full"' in DIAGNOSTICS
    assert "api_provider_test" in DIAGNOSTICS
    assert "api_provider_search_selected" in DIAGNOSTICS
    assert "api_xunlei_preflight" in DIAGNOSTICS
    for forbidden in ("create_transfer", "flash_upload", "download_task", "add_download"):
        assert forbidden not in DIAGNOSTICS
    assert "一键完整诊断" in CONSOLE and "/diagnostics/full" in CONSOLE
    assert "full_diagnostics_last" in CONSOLE

def test_console_is_responsive_and_has_real_actions():
    for token in ("border-radius:18px", '"sm": 6', '"md": 3', "VDataTable", "搜索缺失资源", "秒传预检", "检测资源来源", "刷新观影节点"):
        assert token in CONSOLE
    for endpoint in ("/providers/search/selected", "/providers/test", "/xunlei/flash/preflight", "/viewing/nodes/refresh", "/diagnostics/full"):
        assert endpoint in CONSOLE
    priority = ["① 迅雷秒传", "② 光鸭直存", "③ Magnet", "④ ED2K"]
    positions = [CONSOLE.index(value) for value in priority]
    assert positions == sorted(positions)

def test_config_ui_keeps_models_and_folds_protocol_details():
    for token in ("VExpansionPanels", "接管与保存", "资源来源", "观影与迅雷秒传", "高级设置", "xunlei_captcha_init_json", "viewing_registry_urls"):
        assert token in CONFIG
    for model in ("selected_subscriptions", "save_path", "channel_urls", "magnet_api_sources", "viewing_username", "viewing_password", "xunlei_flash_enabled"):
        assert model in CONFIG
