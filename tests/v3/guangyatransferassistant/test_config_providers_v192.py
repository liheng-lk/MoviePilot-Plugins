from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
CONFIG = PLUGIN / "config_ui_v192.py"
PROVIDERS = PLUGIN / "provider_sources_v192.py"
GYING = PLUGIN / "gying_runtime_v193.py"
FAILOVER = PLUGIN / "gying_failover_v193.py"
HARDENING = PLUGIN / "gying_hardening_v193.py"
SAFETY = PLUGIN / "planner_safety_v190.py"

entry_text = ENTRY.read_text(encoding="utf-8")
config_text = CONFIG.read_text(encoding="utf-8")
provider_text = PROVIDERS.read_text(encoding="utf-8")
gying_text = GYING.read_text(encoding="utf-8")
failover_text = FAILOVER.read_text(encoding="utf-8")
hardening_text = HARDENING.read_text(encoding="utf-8")
safety_text = SAFETY.read_text(encoding="utf-8")


def test_v192_files_parse_and_release_metadata_is_consistent():
    for path, text in (
        (ENTRY, entry_text),
        (CONFIG, config_text),
        (PROVIDERS, provider_text),
        (GYING, gying_text),
        (FAILOVER, failover_text),
        (HARDENING, hardening_text),
        (SAFETY, safety_text),
    ):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.10.5"
    assert 'plugin_version = "1.10.5"' in entry_text
    assert 'build_id = "20260901-r16"' in entry_text
    assert "v1.9.2" in package["history"]


def test_final_config_ui_replaces_stacked_legacy_cards():
    method = config_text.split("    def get_form(self):", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "old_form, defaults = super().get_form()" in method
    assert 'return [{"component": "VForm", "content": [basic, sources, decision, advanced]}], defaults' in method
    for title in ("基础", "资源来源", "资源决策与云添加", "高级"):
        assert f'"{title}"' in method
    assert "old_form[0]" not in method
    assert "content.append" not in method


def test_config_exposes_complete_viewing_node_login_and_cookie_controls():
    for token in (
        '"viewing_enabled"',
        '"viewing_base_url"',
        '"viewing_registry_urls"',
        '"viewing_node_urls"',
        '"viewing_auto_switch"',
        '"viewing_auto_challenge"',
        '"viewing_node_cache_minutes"',
        '"viewing_username"',
        '"viewing_password"',
        '"viewing_cookie"',
        "首选观影节点（可留空）",
        "观影地址发布页",
        "手动备用观影节点",
        "观影节点自动切换",
        "自动完成观影计算验证",
        "观影用户名 / 邮箱",
        "观影密码",
        "观影 Cookie（可选）",
        "https://www.星际穿越.com",
        "https://www.gying.page",
    ):
        assert token in config_text
    assert 'type="password"' in config_text
    form = config_text.split("    def get_form(self):", 1)[1]
    assert '_field("viewing_login_path"' not in form


def test_protocol_level_options_are_moved_out_of_daily_source_controls():
    sources = config_text.split("        sources = self._card(", 1)[1].split("        decision = self._card(", 1)[0]
    advanced = config_text.split("        advanced = self._card(", 1)[1].split("        defaults.update", 1)[0]
    for token in ("viewing_registry_urls", "viewing_node_urls", "viewing_auto_challenge", "xunlei_device_id", "xunlei_captcha_token", "xunlei_captcha_init_json"):
        assert token not in sources
        assert token in advanced
    for token in ("viewing_enabled", "provider_auto_search", "viewing_auto_switch", "xunlei_flash_enabled", "viewing_username", "viewing_password"):
        assert token in sources


def test_config_exposes_multiple_magnet_ed2k_api_sources():
    assert '"magnet_api_sources"' in config_text
    assert "名称|类型|地址|密钥" in config_text
    for kind in ("tgsearch", "limitless", "json", "torznab"):
        assert kind in config_text
        assert kind in provider_text


def test_final_gying_runtime_uses_real_login_search_downurl_and_pow_paths():
    for token in (
        "/user/login",
        "/search?q=",
        "/res/downurl/",
        "/res/pow",
        "_GYING_SEARCH_RE",
        "browser_verified",
        "viewing_session_state",
    ):
        assert token in gying_text
    assert "_discover_gying_nodes" in gying_text
    assert "_gying_node_order" in failover_text
    assert "_LANDING_MARKERS" in failover_text
    assert "CURRENT_CONTENT_SEEDS" in hardening_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaGyingHardeningMixin,", start) < entry_text.index("GuangYaGyingRuntimeMixin,", start)
    assert entry_text.index("GuangYaGyingRuntimeMixin,", start) < entry_text.index("GuangYaProviderSourcesMixin,", start)
    assert 'params = {"t": "search", "q": keyword}' in provider_text
    assert 'headers["X-API-Key"] = token' in provider_text
    assert "ElementTree.fromstring" in provider_text
    assert '"/providers/search"' in provider_text
    assert '"/providers/test"' in provider_text


def test_provider_results_enter_existing_resourcegroup_not_local_downloader():
    assert "super()._dispatch_channel_external_candidates(subscribe)" in provider_text
    assert "if result.get(\"actions\")" in provider_text
    assert "_upsert_source(" in provider_text
    assert "target_episodes=sorted(target)" in provider_text
    assert "_spawn_source_dispatch" in provider_text
    assert "_existing_source" in provider_text
    combined = "\n".join((provider_text, gying_text, failover_text, hardening_text)).lower()
    for forbidden in (
        "from app.chain.download",
        "downloadchain(",
        "qbittorrent",
        "transmission",
        "aria2",
        "bridge_url",
    ):
        assert forbidden not in combined


def test_viewing_secrets_are_not_returned_by_public_provider_or_node_api():
    api = provider_text.split("    def api_provider_search", 1)[1].split("    def get_api", 1)[0]
    assert "_viewing_password" not in api
    assert "_viewing_cookie" not in api
    assert "_magnet_api_sources" not in api
    node_api = gying_text.split("    def api_viewing_nodes(", 1)[1].split("    def api_provider_test", 1)[0]
    assert '"cookie"' not in node_api
    assert "_viewing_password" not in node_api
    assert "_viewing_cookie" not in node_api


def test_provider_config_survives_route_async_save():
    save = safety_text.split("    def _save_config(self)", 1)[1].split("    def _external_resource_allowed", 1)[0]
    for key in (
        "provider_auto_search",
        "provider_timeout",
        "provider_result_limit",
        "provider_proxy",
        "viewing_enabled",
        "viewing_base_url",
        "viewing_login_path",
        "viewing_username",
        "viewing_password",
        "viewing_cookie",
        "viewing_registry_urls",
        "viewing_node_urls",
        "viewing_auto_switch",
        "viewing_auto_challenge",
        "viewing_node_cache_minutes",
        "magnet_api_sources",
    ):
        assert f'"{key}"' in save


def test_runtime_mro_places_complete_gying_before_xunlei_provider_and_planner():
    start = entry_text.index("class GuangYaTransferAssistant")
    order = [
        "GuangYaConfigUiMixin,",
        "GuangYaGyingHardeningMixin,",
        "GuangYaGyingFailoverMixin,",
        "GuangYaGyingRuntimeMixin,",
        "GuangYaXunleiHardeningMixin,",
        "GuangYaXunleiFlashMixin,",
        "GuangYaProviderSourcesMixin,",
        "GuangYaPlannerSafetyMixin,",
        "GuangYaResourcePlannerMixin,",
    ]
    positions = [entry_text.index(token, start) for token in order]
    assert positions == sorted(positions)
