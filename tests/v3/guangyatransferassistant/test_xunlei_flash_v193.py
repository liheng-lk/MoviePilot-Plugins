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
    assert package["version"] == local["version"] == "1.10.11"
    assert 'plugin_version = "1.10.11"' in entry_text
    assert 'build_id = "20260902-r22"' in entry_text
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
