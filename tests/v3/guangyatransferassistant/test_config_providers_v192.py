from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
CONFIG = PLUGIN / "config_ui_v192.py"
PROVIDERS = PLUGIN / "provider_sources_v192.py"
SAFETY = PLUGIN / "planner_safety_v190.py"

entry_text = ENTRY.read_text(encoding="utf-8")
config_text = CONFIG.read_text(encoding="utf-8")
provider_text = PROVIDERS.read_text(encoding="utf-8")
safety_text = SAFETY.read_text(encoding="utf-8")


def test_v192_files_parse_and_release_metadata_is_consistent():
    for path, text in ((ENTRY, entry_text), (CONFIG, config_text), (PROVIDERS, provider_text), (SAFETY, safety_text)):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.9.2"
    assert 'plugin_version = "1.9.2"' in entry_text
    assert 'build_id = "20260901-r4"' in entry_text
    assert "v1.9.2" in package["history"]


def test_final_config_ui_replaces_stacked_legacy_cards():
    method = config_text.split("    def get_form(self):", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "old_form, defaults = super().get_form()" in method
    assert 'return [{"component": "VForm", "content": [basic, sources, decision, advanced]}], defaults' in method
    for title in ("基础", "资源来源", "资源决策与云添加", "高级"):
        assert f'"{title}"' in method
    # 新的最终配置层只借用旧表单的动态 items/defaults，不把旧 content 再 append 回去。
    assert "old_form[0]" not in method
    assert "content.append" not in method


def test_config_exposes_viewing_address_login_and_cookie():
    for token in (
        '"viewing_enabled"',
        '"viewing_base_url"',
        '"viewing_login_path"',
        '"viewing_username"',
        '"viewing_password"',
        '"viewing_cookie"',
        "观影地址",
        "观影用户名 / 邮箱",
        "观影密码",
        "观影 Cookie",
    ):
        assert token in config_text
    assert '"https://www.gying.org"' in config_text
    assert 'type="password"' in config_text


def test_config_exposes_multiple_magnet_ed2k_api_sources():
    assert '"magnet_api_sources"' in config_text
    assert "名称|类型|地址|密钥" in config_text
    for kind in ("tgsearch", "limitless", "json", "torznab"):
        assert kind in config_text
        assert kind in provider_text


def test_provider_search_has_real_viewing_and_api_paths():
    # GYING 搜索与 downurl 取资源链路。
    assert '/s/1---1/' in provider_text
    assert 'res/downurl' in provider_text
    assert "panlist" in provider_text
    # 通用 API 与 Torznab。
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
    assert "_provider_candidate_matches" in provider_text
    combined = provider_text.lower()
    for forbidden in (
        "from app.chain.download",
        "downloadchain(",
        "qbittorrent",
        "transmission",
        "aria2",
        "bridge_url",
    ):
        assert forbidden not in combined


def test_viewing_secrets_are_not_returned_by_provider_api():
    api = provider_text.split("    def api_provider_search", 1)[1].split("    def get_api", 1)[0]
    assert "_viewing_password" not in api
    assert "_viewing_cookie" not in api
    assert "_magnet_api_sources" not in api
    assert "API 不返回观影 Cookie、账号、密码或接口密钥" in api


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
        "magnet_api_sources",
    ):
        assert f'"{key}"' in save


def test_runtime_mro_places_config_and_provider_before_planner():
    start = entry_text.index("class GuangYaTransferAssistant")
    order = [
        "GuangYaConfigUiMixin,",
        "GuangYaProviderSourcesMixin,",
        "GuangYaPlannerSafetyMixin,",
        "GuangYaResourcePlannerMixin,",
    ]
    positions = [entry_text.index(token, start) for token in order]
    assert positions == sorted(positions)
