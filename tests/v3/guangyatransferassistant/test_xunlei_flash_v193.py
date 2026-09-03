from __future__ import annotations

import ast
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
XUNLEI = PLUGIN / "xunlei_flash_v193.py"
XUNLEI_HARDENING = PLUGIN / "xunlei_hardening_v193.py"
GYING = PLUGIN / "gying_runtime_v193.py"
CONFIG = PLUGIN / "config_ui_v192.py"
SAFETY = PLUGIN / "planner_safety_v190.py"

entry_text = ENTRY.read_text(encoding="utf-8")
xunlei_text = XUNLEI.read_text(encoding="utf-8")
xunlei_hardening_text = XUNLEI_HARDENING.read_text(encoding="utf-8")
gying_text = GYING.read_text(encoding="utf-8")
config_text = CONFIG.read_text(encoding="utf-8")
safety_text = SAFETY.read_text(encoding="utf-8")


def _parser_namespace():
    tree = ast.parse(xunlei_text, filename=str(XUNLEI))
    body = []
    wanted_assigns = {"_XUNLEI_URL_RE", "_PASSCODE_RE"}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names.intersection(wanted_assigns):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "parse_xunlei_share":
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "html": html,
        "re": re,
        "parse_qs": parse_qs,
        "urlparse": urlparse,
        "Any": Any,
        "Dict": Dict,
        "List": List,
    }
    exec(compile(module, str(XUNLEI), "exec"), ns)
    return ns


def test_v193_files_parse_and_publish_current_version():
    for path, text in ((ENTRY, entry_text), (XUNLEI, xunlei_text), (XUNLEI_HARDENING, xunlei_hardening_text), (GYING, gying_text), (CONFIG, config_text), (SAFETY, safety_text)):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.12.2"
    assert 'plugin_version = "1.12.2"' in entry_text
    assert 'build_id = "20260903-r48"' in entry_text
    assert "v1.9.3" in package["history"]


def test_xunlei_is_first_acquisition_source_after_complete_gying_session_layer():
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
    method = xunlei_text.split("    def _try_transfer_subscription_inner(", 1)[1].split("    def api_xunlei_flash_test", 1)[0]
    assert method.index("_dispatch_xunlei_flash(subscribe)") < method.index("super()._try_transfer_subscription_inner")
    assert 'if flash.get("handled"):' in method
    assert "观影迅雷分享秒传优先完成" in method
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry_text


def test_viewing_xunlei_parser_reads_share_id_and_passcode():
    parse = _parser_namespace()["parse_xunlei_share"]
    rows = parse("资源：https://pan.xunlei.com/s/ABC_123?pwd=a1B2", label="Demo.S01E03")
    assert len(rows) == 1
    assert rows[0]["share_id"] == "ABC_123"
    assert rows[0]["passcode"] == "a1B2"
    assert rows[0]["type"] == "xunlei"
    assert rows[0]["provider"] == "viewing"

    rows = parse("迅雷：https://pan.xunlei.com/s/XYZ999  提取码：9xY", label="Show")
    assert len(rows) == 1
    assert rows[0]["share_id"] == "XYZ999"
    assert rows[0]["passcode"] == "9xY"


def test_final_viewing_search_extracts_xunlei_from_real_search_downurl_chain():
    assert "def _search_viewing_xunlei" in gying_text
    final_search = gying_text.split("    def _search_viewing_xunlei(", 1)[1].split("    # ------------------------------------------------------------------\n    # 对外诊断 API", 1)[0]
    assert "_gying_raw_results(keyword)" in final_search
    assert "_XUNLEI_URL_RE" in final_search
    assert '"type": "xunlei"' in final_search
    assert '"provider": "viewing"' in final_search
    raw = gying_text.split("    def _gying_raw_results(", 1)[1].split("    def _search_viewing(", 1)[0]
    assert "/search?q=" in raw
    assert "_gying_detail" in raw
    assert "/res/downurl/" in gying_text


def test_xunlei_share_protocol_gets_pass_token_then_detail_and_file_hash():
    for endpoint in (
        "/drive/v1/share",
        "/drive/v1/share/detail",
        "/drive/v1/share/file_info",
    ):
        assert endpoint in xunlei_text or endpoint in xunlei_hardening_text
    share = xunlei_text.split("    def _xunlei_share_info(", 1)[1].split("    def _xunlei_normalize_file", 1)[0]
    assert 'params["pass_code"] = passcode' in share
    assert 'body.get("pass_code_token")' in share
    combined_headers = xunlei_hardening_text.split("    def _xunlei_headers(", 1)[1].split("    @staticmethod\n    def _merge_xunlei_file", 1)[0]
    assert '"x-device-id"' in combined_headers
    assert '"x-guid"' in combined_headers
    assert '"x-captcha-token"' in combined_headers
    assert 'headers.pop("Authorization", None)' in combined_headers


def test_hash_path_reuses_reference_gcid_and_three_20kb_sample_cid():
    normalize = xunlei_text.split("    def _xunlei_normalize_file(", 1)[1].split("    def _xunlei_share_files", 1)[0]
    assert 'raw.get("hash")' in normalize
    assert 'raw.get("md5")' in normalize
    cid = xunlei_text.split("    def _xunlei_compute_triple_cid(", 1)[1].split("    def _guangya_userres_request", 1)[0]
    assert "20 * 1024" in cid
    assert "file_size // 3" in cid
    assert "file_size - sample_size" in cid
    assert "hashlib.sha1" in cid
    assert '"Range": f"bytes={start}-{end}"' in cid


def test_guangya_flash_uses_userres_rapid_transfer_not_local_downloader_or_oss():
    rapid = xunlei_text.split("    def _rapid_transfer_xunlei_file(", 1)[1].split("    def _xunlei_state", 1)[0]
    assert "/userres/v1/get_res_center_token" in rapid
    assert "/userres/v1/check_can_flash_upload" in rapid
    assert "/userres/v1/file/get_info_by_task_id" in xunlei_text
    assert '"capacity": 2' in rapid
    assert 'code in (156, "156")' in rapid
    assert "/userres/v1/file/delete_upload_task" in rapid
    assert "不做 OSS/本地中转，回退下一来源" in rapid
    combined = "\n".join((xunlei_text, xunlei_hardening_text, gying_text)).lower()
    for forbidden in (
        "from app.chain.download",
        "downloadchain(",
        "qbittorrent",
        "transmission",
        "aria2",
        "/userres/v1/flash_upload",
        "tryuploadoss",
        "content-range",
    ):
        assert forbidden not in combined


def test_xunlei_uses_existing_missing_episode_planner_and_reservations():
    assert "_planner_file_selection" in xunlei_text
    assert "_subscription_missing_episodes" in xunlei_text
    assert "_subscription_resource_allowed" in xunlei_text
    assert "_remember_episode_facts" in xunlei_text
    pending = xunlei_text.split("    def _pending_reservations(", 1)[1].split("    def _dispatch_xunlei_flash", 1)[0]
    assert "super()._pending_reservations" in pending
    assert 'merged["episodes"]' in pending
    assert 'merged["movie"]' in pending
    assert "秒传" in json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]["history"]["v1.9.3"]


def test_config_exposes_xunlei_runtime_credentials_and_fixed_priority():
    for token in (
        '"xunlei_flash_enabled"',
        '"xunlei_flash_max_files"',
        '"xunlei_client_id"',
        '"xunlei_device_id"',
        '"xunlei_captcha_token"',
        '"xunlei_captcha_init_json"',
        "迅雷秒传优先",
        "迅雷 captcha/init 请求体（可选兜底）",
        "观影迅雷秒传 > 光鸭分享 > Magnet > ED2K",
    ):
        assert token in config_text
    save = safety_text.split("    def _save_config(self)", 1)[1].split("    def _external_resource_allowed", 1)[0]
    for key in (
        "xunlei_flash_enabled",
        "xunlei_flash_max_files",
        "xunlei_client_id",
        "xunlei_device_id",
        "xunlei_captcha_token",
        "xunlei_captcha_init_json",
    ):
        assert f'"{key}"' in save


def test_public_xunlei_state_and_test_api_do_not_return_secret_config():
    api = xunlei_text.split("    def api_xunlei_flash_test", 1)[1].split("    def get_api", 1)[0]
    assert '"xunlei_captcha_token"' not in api
    assert '"xunlei_captcha_init_json"' not in api
    assert '"xunlei_device_id"' not in api
    assert '"with_captcha"' in api
    runtime = xunlei_hardening_text.split("    def api_xunlei_runtime_status", 1)[1].split("    def get_api", 1)[0]
    assert '"captcha_token"' not in runtime
    assert '"device_id"' not in runtime
    assert '"/xunlei/flash/test"' in xunlei_text
    assert '"/xunlei/flash/state"' in xunlei_text
    assert '"/xunlei/runtime/status"' in xunlei_hardening_text


def test_full_json_generation_is_preserved_but_import_is_pruned_to_verified_missing():
    batch = xunlei_text.split("    def _xunlei_json_batch_indexes_v1118(", 1)[1].split(
        "    def _xunlei_reservation(", 1
    )[0]
    dispatch = xunlei_text.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _try_transfer_subscription_inner(", 1
    )[0]
    assert "_is_video(path) or _is_subtitle(path)" in batch
    assert "indexes = self._xunlei_json_batch_indexes_v1118(enriched)" in dispatch
    assert "batch_template = self._xunlei_make_json_v1117(batch_rows)" in dispatch
    assert "_xunlei_json_identity_matches_v1123" in dispatch
    assert "_xunlei_import_json_batch_v1123" in dispatch
    assert "import_indexes = [index for index in indexes if index in planned_index_set]" in dispatch
    assert "include_indexes=import_positions" in dispatch
    assert "if batch_index not in import_positions:" in dispatch
    assert "完整 JSON 不裁剪，planner 只控制实际导入索引" in dispatch
    assert "batch_results" in dispatch
    assert 'if not indexes or bool(selection.get("ambiguous"))' not in dispatch
    assert 'if not row.get("gcid") or _safe_int(row.get("size"), 0) <= 0:' in dispatch
    assert 'not row.get("cid") and not row.get("download_url")' not in dispatch


def test_xunlei_syncs_library_before_planning_and_rejects_ambiguous_tv_batch():
    dispatch = xunlei_text.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _try_transfer_subscription_inner(", 1
    )[0]
    assert dispatch.index("_sync_media_library_progress(subscribe)") < dispatch.index(
        "missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe)"
    )
    assert 'if bool(selection.get("ambiguous")) or not planned_indexes:' in dispatch
    assert "完整模板已生成但不导入" in dispatch
    assert "continue" in dispatch.split('if bool(selection.get("ambiguous")) or not planned_indexes:', 1)[1]


def test_successful_xunlei_batch_blocks_fallback_for_tv_and_movie():
    episode_method = xunlei_text.split("    def _xunlei_file_episodes(", 1)[1].split(
        "    @staticmethod\n    def _xunlei_movie_primary_index_v1119", 1
    )[0]
    movie_method = xunlei_text.split("    def _xunlei_movie_primary_index_v1119(", 1)[1].split(
        "    def _select_xunlei_files", 1
    )[0]
    dispatch = xunlei_text.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _try_transfer_subscription_inner", 1
    )[0]
    assert "package_paths=package_paths" in episode_method
    assert "max(videos, key=" in movie_method
    assert "movie_features.intersection(successful_indexes)" in dispatch
    assert "video_success == len(selected_videos)" not in dispatch


def test_provider_match_rejects_wrong_year_and_season_before_cloud_add():
    provider = (PLUGIN / "provider_sources_v192.py").read_text(encoding="utf-8")
    matcher = provider.split("    def _provider_candidate_matches(", 1)[1].split(
        "    def _provider_keyword", 1
    )[0]
    viewing = (PLUGIN / "viewing_dispatch_v1113.py").read_text(encoding="utf-8")
    dispatch = viewing.split("    def _dispatch_viewing_external_v1113(", 1)[1].split(
        "    def ", 1
    )[0]
    assert "actual_years" in matcher
    assert "expected_year not in actual_years" in matcher
    assert "expected_season not in seasons" in matcher
    assert "is_movie and seasons" in matcher
    assert "prior_movie_sources" in dispatch
    assert "等待成功/失败核验后再决定是否回退" in dispatch


def test_cloud_candidate_and_verified_gap_are_reported_before_supplement():
    viewing = (PLUGIN / "viewing_dispatch_v1113.py").read_text(encoding="utf-8")
    runtime = (PLUGIN / "runtime_fix_v1113.py").read_text(encoding="utf-8")
    assert "🎯 已选择光鸭云资源" in viewing
    assert "计划补充" in viewing
    assert "期间不会并行提交相似资源" in viewing
    assert "成功集数" in runtime
    assert "仍缺集数" in runtime
    assert "只会从其它来源补充上述缺集" in runtime
    assert "⚠️ 光鸭云添加未完成" in runtime
    assert "这些集仍保持缺失，只允许下一个来源补充这些集" in runtime


def test_verified_movie_receipt_records_fact_and_finishes_subscription():
    governance = (PLUGIN / "governance_v1114.py").read_text(encoding="utf-8")
    helper = governance.split("    def _remember_verified_movie_v1121(", 1)[1].split(
        "    def _poll_offline_source", 1
    )[0]
    poll = governance.split("    def _poll_offline_source(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 质量门禁", 1
    )[0]
    dispatch = governance.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _dispatch_viewing_external_v1113", 1
    )[0]
    assert "_remember_media_facts" in helper
    assert "_movie_transfer_confirmed" in helper
    assert "真实完成回执" in helper
    assert '_remember_verified_movie_v1121(subscribe, "guangya_offline"' in poll
    assert "_finish_subscription_if_complete(subscribe)" in poll
    assert "subscription_completed_notified_at" in poll
    assert "✅ 电影订阅已完成" in poll
    assert '_remember_verified_movie_v1121(subscribe, "xunlei_flash"' in dispatch


def test_handled_result_hard_stops_viewing_magnet_fallback():
    viewing = (PLUGIN / "viewing_logging_v1113.py").read_text(encoding="utf-8")
    method = viewing.split("    def _try_transfer_subscription_inner(", 1)[1].split(
        "\n\n__all__", 1
    )[0]
    handled = method.index('if bool(result.get("handled")):')
    gap = method.index("gap = self._viewing_gap_v1113(subscribe)")
    dispatch = method.index("_dispatch_viewing_external_v1113(subscribe)")
    assert handled < gap < dispatch
    assert "前序结果 handled=True，硬阻断观影 Magnet/ED2K" in method


def test_any_verified_non_auxiliary_movie_video_completes_xunlei():
    helper = xunlei_text.split("    def _xunlei_movie_feature_indexes_v1122(", 1)[1].split(
        "    def _select_xunlei_files", 1
    )[0]
    dispatch = xunlei_text.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _try_transfer_subscription_inner", 1
    )[0]
    assert "is_auxiliary_media_v1105" in helper
    assert "movie_features.intersection(successful_indexes)" in dispatch
    assert "电影正片已确认成功/已存在" in dispatch


def test_xunlei_json_real_identity_blocks_cross_media_import():
    helper = xunlei_text.split("    def _xunlei_json_identity_matches_v1123(", 1)[1].split(
        "    def _select_xunlei_files", 1
    )[0]
    dispatch = xunlei_text.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _try_transfer_subscription_inner", 1
    )[0]
    assert 'info.get("title")' in helper
    assert 'template.get("files")' in helper
    assert "expected_cjk and actual_cjk and not direct_match" in helper
    assert "迅雷 JSON 实际媒体不匹配" in helper
    assert "迅雷 JSON 年份不匹配" in helper
    assert "迅雷 JSON 季号不匹配" in helper
    assert dispatch.index("_xunlei_json_identity_matches_v1123") < dispatch.index("_xunlei_import_json_batch_v1123")
    assert "整批拒绝导入" in dispatch


def test_xunlei_full_share_limit_does_not_collapse_to_one_file():
    init = xunlei_text.split("    def init_plugin(", 1)[1].split(
        "    def _search_viewing_xunlei", 1
    )[0]
    listing = xunlei_text.split("    def _xunlei_share_files(", 1)[1].split(
        "    def _xunlei_file_info", 1
    )[0]
    assert "if configured_max_files <= 1:" in init
    assert "configured_max_files = 500" in init
    assert "min(configured_max_files, 5000)" in init
    assert "分享目录递归完成" in listing
    assert "JSON 可能被截断" in listing