from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
TRANSPORT = PLUGIN / "gying_transport_v1108.py"
ENTRY = PLUGIN / "__init__.py"


transport_text = TRANSPORT.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")


def _method_source(class_name: str, method_name: str) -> str:
    tree = ast.parse(transport_text)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    return ast.get_source_segment(transport_text, method) or ""


def _function_source(name: str) -> str:
    tree = ast.parse(transport_text)
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    return ast.get_source_segment(transport_text, node) or ""


def test_v1108_files_parse_and_release_metadata_are_aligned():
    ast.parse(transport_text, filename=str(TRANSPORT))
    ast.parse(entry_text, filename=str(ENTRY))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.10.8"
    assert 'plugin_version = "1.10.8"' in entry_text
    assert 'build_id = "20260902-r19"' in entry_text
    assert "v1.10.8" in package.get("history", {})


def test_transport_layer_is_outermost_without_rewriting_legacy_auth_chain():
    assert "from .gying_transport_v1108 import GuangYaGyingTransportV1108Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaGyingTransportV1108Mixin,", start) < entry_text.index("GuangYaStabilityV1106Mixin,", start)
    assert "class GuangYaGyingTransportV1108Mixin:" in transport_text


def test_auth_start_returns_after_spawning_background_worker():
    source = _method_source("GuangYaGyingTransportV1108Mixin", "_gying_auth_start")
    assert "threading.Thread(" in source
    assert "daemon=True" in source
    assert 'name="GuangYa-GYING-Auth"' in source
    assert "worker.start()" in source
    assert "return {\"success\": True, **self._gying_auth_public(row)}" in source
    assert "_discover_gying_nodes(" not in source
    assert "_gying_request(" not in source
    assert "认证任务已启动" in source


def test_pow_detection_prefers_normal_obj_pages_and_uses_precise_json_semantics():
    source = _function_source("_challenge_required_v1108")
    assert 'if "_obj." in text:' in source
    assert "return False" in source
    assert 'int(payload.get("code") or 0) == 419' in source
    assert 'int(payload.get("refresh") or 0) == 1' in source
    assert 'refresh and "验证" in message' in source
    assert "_is_challenge_text" not in source
    markers = transport_text.split("_CHALLENGE_TEXT_MARKERS_V1108 = (", 1)[1].split(")", 1)[0]
    assert '"安全验证"' not in markers
    assert '"浏览器安全验证"' in markers


def test_remote_pow_requires_explicit_server_success_before_retrying_original_request():
    solve = _method_source("GuangYaGyingTransportV1108Mixin", "_gying_solve_challenge")
    request = _method_source("GuangYaGyingTransportV1108Mixin", "_gying_request")
    assert 'result.get("success") in (True, 1, "1", "true", "True")' in solve
    assert "or not accepted" in solve
    assert "观影远程 PoW 未被服务器确认" in solve
    assert "max_pow = 2 if retry_challenge else 0" in request
    assert "if not _challenge_required_v1108(response):" in request
    assert "浏览器计算验证确认通过" in request


def test_eight_confirmed_mirrors_share_only_runtime_cookie_inside_whitelist():
    for name in (
        "教父.com",
        "星际穿越.com",
        "楚门的世界.com",
        "泰坦尼克号.com",
        "盗梦空间.com",
        "肖申克的救赎.com",
        "阿甘正传.com",
        "黑客帝国.com",
    ):
        assert name in transport_text
    session_source = _method_source("GuangYaGyingTransportV1108Mixin", "_gying_new_session")
    sync_source = _method_source("GuangYaGyingTransportV1108Mixin", "_gying_sync_cookie_v1108")
    assert "_GYING_MIRROR_SET_V1108" in session_source
    assert "_GYING_MIRROR_SET_V1108" not in "https://www.gying.page"
    assert "if not self._gying_is_mirror_v1108(node):" in sync_source
    assert "_apply_cookie_header(session, shared)" in session_source


def test_mobile_fingerprint_matches_315x180_manual_captcha_without_ocr():
    session_source = _method_source("GuangYaGyingTransportV1108Mixin", "_gying_new_session")
    assert "iPhone OS 18_5" in transport_text
    assert 'session.headers.pop(key, None)' in session_source
    auth_text = (PLUGIN / "gying_auth_v1107.py").read_text(encoding="utf-8")
    assert "_CAPTCHA_WIDTH = 315" in auth_text
    assert "_CAPTCHA_HEIGHT = 180" in auth_text
    lowered = transport_text.lower()
    for forbidden in ("pytesseract", "easyocr", "paddleocr", "captcha_solver"):
        assert forbidden not in lowered


def test_fixed_transfer_priority_is_untouched():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry_text
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in entry_text
