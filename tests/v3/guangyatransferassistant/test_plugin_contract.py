import ast
import hashlib
import html
import json
import re
import shlex
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ROUTING = ROOT / "plugins.v3" / "guangyatransferassistant" / "routing_v170.py"
LEGACY = ROOT / "plugins.v3" / "guangyatransferassistant" / "legacy.py"
entry_text = ENTRY.read_text(encoding="utf-8")
routing_text = ROUTING.read_text(encoding="utf-8")
legacy_text = LEGACY.read_text(encoding="utf-8")

ast.parse(entry_text)
ast.parse(routing_text)
legacy_tree = ast.parse(legacy_text)

legacy_nodes = []
for node in legacy_tree.body:
    if isinstance(node, ast.ClassDef):
        break
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef)):
        if isinstance(node, ast.FunctionDef):
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
        legacy_nodes.append(node)
legacy_mod = ast.Module(body=legacy_nodes, type_ignores=[])
ast.fix_missing_locations(legacy_mod)
legacy_ns = {
    "hashlib": hashlib, "html": html, "re": re,
    "parse_qs": parse_qs, "urlencode": urlencode, "unquote": unquote,
    "urljoin": urljoin, "urlsplit": urlsplit, "urlunsplit": urlunsplit,
    "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List,
    "Optional": Optional, "Tuple": Tuple,
}
exec(compile(legacy_mod, str(LEGACY), "exec"), legacy_ns)


class _MediaTypeStub:
    MOVIE = "movie"
    TV = "tv"


routing_tree = ast.parse(routing_text)
routing_nodes = []
for node in routing_tree.body:
    if isinstance(node, ast.ClassDef):
        break
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef)):
        if isinstance(node, ast.FunctionDef):
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
        routing_nodes.append(node)
routing_mod = ast.Module(body=routing_nodes, type_ignores=[])
ast.fix_missing_locations(routing_mod)
routing_ns = {
    "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
    "MediaType": _MediaTypeStub, "re": re, "shlex": shlex,
}
exec(compile(routing_mod, str(ROUTING), "exec"), routing_ns)


def test_versions_and_layered_legacy_contract():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.12.11"
    assert local["version"] == "1.12.11"
    assert 'plugin_version = "1.12.11"' in entry_text
    assert 'build_id = "20260905-r57"' in entry_text
    assert 'plugin_version = "1.7.0"' in routing_text
    assert 'plugin_version = "1.6.5"' in legacy_text
    assert "from .routing_v170 import GuangYaTransferAssistant as _RoutingV170Assistant" in entry_text
    assert "from .legacy import GuangYaTransferAssistant as _LegacyGuangYaTransferAssistant" in routing_text
    assert "GuangYaConfigUiMixin" in entry_text
    assert "GuangYaGyingFailoverMixin" in entry_text
    assert "GuangYaGyingRuntimeMixin" in entry_text
    assert "GuangYaXunleiFlashMixin" in entry_text
    assert "GuangYaProviderSourcesMixin" in entry_text
    assert "GuangYaPlannerSafetyMixin" in entry_text
    assert "GuangYaResourcePlannerMixin" in entry_text
    assert "GuangYaGyingTransportV1108Mixin" in entry_text
    assert "GuangYaGyingAutoLoginV1109Mixin" in entry_text


def test_legacy_channel_hidden_visible_and_exact_tmdb_matching():
    page = '''<div data-post="regengguangya/201">名称：花开锦绣 (2026)<br>TMDB: 287496
    <a href="https://www.guangyapan.com/s/a201">查看资源</a></div>
    <div data-post="regengguangya/202">名称：完全不同 (2025)<br>TMDB: 999999
    <a href="https://www.guangyapan.com/s/a202">查看资源</a></div>'''
    items = legacy_ns["_extract_channel_entries"](page, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 2
    first = next(item for item in items if item["share_id"] == "a201")
    assert first["tmdb_id"] == "287496"
    assert legacy_ns["_entry_matches_subscription"](first, "标题不同也由ID确认", 2026, 1, "themoviedb", "287496") is True
    assert legacy_ns["_entry_matches_subscription"](first, "花开锦绣", 2026, 1, "themoviedb", "999999") is False
    assert "按钮" in first["link_style"]


def test_legacy_episode_path_and_asset_identity_regression():
    season, episodes = legacy_ns["_episode_numbers"]("Show.S01E23-E25.2160p.WEB-DL.mkv")
    assert season == 1 and episodes == [23, 24, 25]
    _, episodes = legacy_ns["_episode_numbers"]("第8-10集.mp4")
    assert episodes == [8, 9, 10]
    assert legacy_ns["_safe_relative_path"]("../../Season 1/../E01.mkv") == "Season 1/E01.mkv"
    old_style = hashlib.sha256("season 1/e01.mkv|100".encode("utf-8")).hexdigest()
    assert legacy_ns["_asset_identity"]("Season 1/E01.mkv", 100) == old_style
    assert legacy_ns["_asset_identity"]("Season 1/E01.mkv", 100, "abc") != old_style


def test_legacy_transfer_state_machine_is_preserved():
    for token in (
        "/nd.bizuserres.s/v1/restore_share",
        "transfer_inventory",
        "processed_entries",
        "media_facts",
        "transfer_jobs",
        "_verify_restored_group",
        "_sync_media_library_progress",
        "SubscribeChain().finish_subscribe_or_not",
        "固定转存路线不触发原生下载",
    ):
        assert token in legacy_text, token


def test_direct_command_parser():
    parse = routing_ns["_parse_direct_subscribe_args"]
    parsed = parse('"沙丘" 2021 movie')
    assert parsed["title"] == "沙丘"
    assert parsed["year"] == "2021"
    assert parsed["mtype"] == _MediaTypeStub.MOVIE
    parsed = parse("藏海传 tv S02 2026")
    assert parsed["title"] == "藏海传" and parsed["season"] == 2
    assert parsed["mtype"] == _MediaTypeStub.TV
    parsed = parse("tmdb:438631 movie")
    assert parsed["tmdb_id"] == "438631" and parsed["title"] == ""


def test_search_all_entry_hard_routing_contract():
    for token in (
        "SubscribeChain.search = guarded_search",
        "_guangya_route_guard",
        "_guangya_original_search",
        "_guangya_plugin_ref",
        "_guard_subscribe_search",
        "_guard_one_subscription",
        "_is_guangya_route",
        "sids: Optional[tuple[int, ...]]",
        "全入口硬分流",
        "不会进入原生下载搜索",
    ):
        assert token in routing_text, token
    guard = routing_text.split("    def _guard_subscribe_search(", 1)[1].split("    @staticmethod\n    def _now_text", 1)[0]
    assert "route_subs" in guard and "native_ids" in guard
    assert "_guard_one_subscription" in guard
    assert "_call_original_search" in guard


def test_rss_match_guard_and_final_download_circuit_breaker():
    for token in (
        "SubscribeChain.match = guarded_match",
        "_guangya_match_guard",
        "RSS硬分流",
        "_SubscribeChain__download_best_version_with_full_pack_first",
        "_guangya_download_guard",
        "下载断路器",
        "return [], no_exists or {}",
        "固定转存路线只允许光鸭转存",
    ):
        assert token in entry_text, token
    assert "all(plugin._is_guangya_route(item) for item in active)" in entry_text
    assert "subscribe is not None and plugin._is_guangya_route(subscribe)" in entry_text


def test_new_route_immediately_forces_channel_refresh():
    assert "_spawn_route_prime" in routing_text
    assert 'trigger="新加入转存路线"' in routing_text
    assert "refresh_channels(force=True)" in routing_text
    assert "_cached_matches_for_subscription(subscribe)" in routing_text
    assert "【立即检查】" in routing_text


def test_message_direct_subscription_and_management_commands():
    for token in (
        '"cmd": "/gysub"',
        '"cmd": "/gystatus"',
        '"cmd": "/gynative"',
        "EventType.PluginAction",
        "MediaChain().search",
        "MediaSource.TMDB",
        "SubscribeChain().add",
        "message=False",
        "_provisional_routes",
        "_spawn_command_transfer",
    ):
        assert token in routing_text, token
    assert "只走光鸭转存，MoviePilot 原生下载搜索已阻断" in routing_text


def test_release_native_does_not_reload_plugin_inside_http_action():
    removal = routing_text.split("    def _remove_selected_subscription(", 1)[1].split("    def _spawn_route_prime(", 1)[0]
    assert "_queue_route_config_persist()" in removal
    assert "_save_config()" not in removal
    persist = routing_text.split("    def _queue_route_config_persist(", 1)[1].split("    def _add_selected_subscription(", 1)[0]
    assert "threading.Timer" in persist
    assert "route_membership_pending" in persist
    assert "self._save_config()" in persist


def test_page_actions_use_v3_bearer_auth_without_api_secret_params():
    assert "return force_bear_auth(super().get_api())" in entry_text
    assert "strip_page_api_secrets(pages)" in entry_text
    assert "from .page_auth_v172 import force_bear_auth, strip_page_api_secrets" in entry_text


def test_route_guards_and_health_contract_remain_active():
    assert "固定分流路由健康" in routing_text
    assert "route_health" in routing_text
    assert "last_guarded_at" in routing_text
    assert "待落盘" in routing_text
    assert "最近结果" in routing_text
    assert "_guangya_match_guard" in entry_text
    assert "最终下载断路器" in entry_text
    assert "光鸭直接转存 > Magnet > ED2K" in entry_text
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry_text


def test_no_silent_native_fallback_for_selected_search_route():
    one = routing_text.split("        if sid:", 1)[1].split("        if sids is not None:", 1)[0]
    assert "self._is_guangya_route(subscribe)" in one
    assert "self._guard_one_subscription" in one
    selected_branch = one.split("if subscribe and self._is_guangya_route(subscribe):", 1)[1]
    assert "return None" in selected_branch
