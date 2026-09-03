from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
DISPATCH = PLUGIN / "viewing_dispatch_v1113.py"
LOGGING = PLUGIN / "viewing_logging_v1113.py"
MULTI = PLUGIN / "multisource_v180.py"
PLUGIN_JSON = PLUGIN / "plugin.json"

entry_text = ENTRY.read_text(encoding="utf-8")
dispatch_text = DISPATCH.read_text(encoding="utf-8")
logging_text = LOGGING.read_text(encoding="utf-8")
multi_text = MULTI.read_text(encoding="utf-8")


def test_v1113_files_parse_and_release_is_published():
    for path, text in ((ENTRY, entry_text), (DISPATCH, dispatch_text), (LOGGING, logging_text)):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.11.1"
    assert 'plugin_version = "1.11.1"' in entry_text
    assert 'build_id = "20260903-r42"' in entry_text
    assert "v1.10.13" in package["history"]


def test_v1113_mro_enables_logging_then_dispatch_before_old_gying_protocol():
    assert "from .viewing_logging_v1113 import GuangYaViewingLoggingV1113Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    assert entry_text.index("GuangYaViewingLoggingV1113Mixin,", start) < entry_text.index(
        "GuangYaGyingProtocolV1106Mixin,", start
    )
    assert "class GuangYaViewingLoggingV1113Mixin(" in logging_text
    assert "GuangYaViewingDispatchV1113Mixin," in logging_text
    assert "GuangYaXunleiJsonPipelineV1117Mixin," in logging_text
    assert "GuangYaXunleiIntegrityV1116Mixin," in logging_text


def test_v1113_valid_btih_is_not_discarded_only_because_downlist_k_drifted():
    detail = dispatch_text.split("    def _gying_detail(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 远端命名", 1
    )[0]
    assert "_BTIH_V1113.fullmatch(btih)" in detail
    assert "kinds[index] = 0" in detail
    assert "Magnet字段兼容" in detail
    assert "后续交给光鸭原生云添加" in detail


def test_v1113_viewing_magnet_and_ed2k_are_bound_and_dispatched_to_native_cloudcollection():
    planner = dispatch_text.split("    def _dispatch_viewing_external_v1113(", 1)[1].split(
        "    def _try_transfer_subscription_inner(", 1
    )[0]
    assert "_gying_raw_results" in dispatch_text
    assert "normalize_source_uri" in dispatch_text
    assert 'source_type not in {"magnet", "ed2k"}' in dispatch_text
    assert "_provider_candidate_matches(subscribe, candidate)" in planner
    assert "self._upsert_source(" in planner
    assert 'origin="viewing_auto"' in planner
    assert "self._spawn_source_dispatch(source_id)" in planner
    assert "执行器=光鸭cloudcollection" in planner
    assert '"/cloudcollection/v1/create_task"' in multi_text
    assert "DownloadChain(" not in dispatch_text


def test_v1113_xunlei_is_flash_only_and_never_becomes_normal_download():
    xunlei_filter = dispatch_text.split("    def _viewing_external_candidates_v1113(", 1)[1].split(
        "    def _dispatch_viewing_external_v1113(", 1
    )[0]
    flash = dispatch_text.split("    def _rapid_transfer_xunlei_file(", 1)[1].split(
        "    def _dispatch_xunlei_flash(", 1
    )[0]
    assert 'if "pan.xunlei.com/s/" in lowered:' in xunlei_filter
    assert 'counts["xunlei"] += 1' in xunlei_filter
    assert "super()._rapid_transfer_xunlei_file" in flash
    assert "只尝试秒传，不做普通下载" in flash
    for forbidden in ("DownloadChain(", "downloadchain(", "oss2", "aria2", "qbittorrent"):
        assert forbidden.lower() not in dispatch_text.lower()


def test_v1113_name_keeps_original_and_appends_search_identity_before_extension():
    helper = dispatch_text.split("def _append_tag_to_name_v1113(", 1)[1].split(
        "\n\n\nclass GuangYaViewingDispatchV1113Mixin", 1
    )[0]
    resolve = dispatch_text.split("    def _resolve_offline_source(", 1)[1].split(
        "    @staticmethod\n    def _rename_result_ok_v1113", 1
    )[0]
    poll = dispatch_text.split("    def _poll_offline_source(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 迅雷", 1
    )[0]
    assert 'marker = f" [{extra}]"' in helper
    assert 'return f"{stem}{marker}{suffix}"[:limit]' in helper
    assert "source[\"label\"] = desired" in resolve
    assert "requested_name=desired" in resolve
    assert "client, _ = self._get_guangya_runtime()" in poll
    assert 'getattr(client, "rename", None)' in poll
    assert "/nd.bizuserres.s/v1/file/rename" in poll


def test_v1113_partial_success_does_not_hide_remaining_missing_episodes():
    method = logging_text.split("    def _try_transfer_subscription_inner(", 1)[1]
    gap = logging_text.split("    def _viewing_gap_v1113(", 1)[1].split(
        "    def _try_transfer_subscription_inner(", 1
    )[0]
    assert "missing - reserved - claimed" in gap
    assert "if bool(gap.get(\"covered\")):" in method
    assert "self._dispatch_viewing_external_v1113(subscribe)" in method
    assert "前序链未完整覆盖" in method


def test_v1113_full_logs_cover_search_flash_cloudadd_poll_naming_and_errors():
    combined = dispatch_text + "\n" + logging_text
    for marker in (
        "【观影执行】",
        "【迅雷秒传】",
        "【原生云添加】",
        "【命名】",
        "失败明细",
        "观影任务轮询结果",
        "规划结束",
    ):
        assert marker in combined
