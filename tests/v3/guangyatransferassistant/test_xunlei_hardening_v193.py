from __future__ import annotations

import ast
import hashlib
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
HARDENING = PLUGIN / "xunlei_hardening_v193.py"

entry_text = ENTRY.read_text(encoding="utf-8")
text = HARDENING.read_text(encoding="utf-8")


def _pure_namespace():
    tree = ast.parse(text, filename=str(HARDENING))
    body = []
    wanted_assigns = {"_XUNLEI_CAPTCHA_SALTS"}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names.intersection(wanted_assigns):
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "build_xunlei_captcha_signature":
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {"hashlib": hashlib, "time": time, "Optional": Optional}
    exec(compile(module, str(HARDENING), "exec"), ns)
    return ns


def test_xunlei_hardening_parses_and_precedes_flash_layer():
    ast.parse(text, filename=str(HARDENING))
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaXunleiHardeningMixin,", start) < entry_text.index("GuangYaXunleiFlashMixin,", start)
    assert 'build_id = "20260904-r52"' in entry_text


def test_signed_captcha_builder_matches_nine_round_reference():
    ns = _pure_namespace()
    build = ns["build_xunlei_captcha_signature"]
    salts = ns["_XUNLEI_CAPTCHA_SALTS"]
    timestamp = 1788235200123
    client_id = "demo-client"
    version = "1.10.0.2633"
    package = "com.xunlei.browser"
    device = "0123456789abcdef0123456789abcdef"
    content = f"{client_id}{version}{package}{device}{timestamp}"
    for salt in salts:
        content = hashlib.md5((content + salt).encode("utf-8")).hexdigest()
    assert build(client_id, version, package, device, timestamp) == (str(timestamp), "1." + content)
    assert len(salts) == 9


def test_runtime_device_is_stable_and_manual_token_without_device_is_not_mismatched():
    init = text.split("    def init_plugin(", 1)[1].split("    def _xunlei_runtime_state_save", 1)[0]
    assert 'self.get_data("xunlei_runtime_state")' in init
    assert "secrets.token_hex(16)" in init
    assert 'self.save_data("xunlei_runtime_state", state)' in init
    assert "manual_token_missing_device" in init
    assert 'self._xunlei_runtime_captcha_token = ""' in init


def test_captcha_auto_init_uses_consistent_client_device_profile():
    refresh = text.split("    def _refresh_xunlei_captcha(", 1)[1].split("    def _xunlei_headers", 1)[0]
    assert "XUNLEI_CAPTCHA_INIT" in refresh
    assert "build_xunlei_captcha_signature" in refresh
    assert '"captcha_sign": signature' in refresh
    assert '"x-device-id": self._xunlei_runtime_device_id' in refresh
    assert 'self._xunlei_runtime_client_id = client_id' in refresh
    headers = text.split("    def _xunlei_headers(", 1)[1].split("    @staticmethod\n    def _merge_xunlei_file", 1)[0]
    assert '"x-client-id"' in headers
    assert '"x-device-id"' in headers
    assert '"x-guid"' in headers
    assert '"x-captcha-token"' in headers
    assert 'headers.pop("Authorization", None)' in headers


def test_share_hash_fallback_requeries_same_parent_without_audit():
    fallback = text.split("    def _xunlei_detail_hash_fallback(", 1)[1].split("    def _xunlei_file_info", 1)[0]
    assert '"/drive/v1/share/detail"' in fallback
    assert '"parent_id": parent_id' in fallback
    assert '"with_audit": "false"' in fallback
    assert 'str(raw.get("id") or raw.get("file_id") or "") != file_id' in fallback
    file_info = text.split("    def _xunlei_file_info(", 1)[1].split("    def api_xunlei_runtime_status", 1)[0]
    assert "super()._xunlei_file_info" in file_info
    assert "_xunlei_detail_hash_fallback" in file_info


def test_xunlei_runtime_status_exposes_only_booleans_and_mode_not_secrets():
    public = text.split("    def api_xunlei_runtime_status", 1)[1].split("    def get_api", 1)[0]
    assert '"captcha_ready"' in public
    assert '"device_ready"' in public
    assert '"captcha_mode"' in public
    assert '"captcha_token"' not in public
    assert '"device_id"' not in public
    assert '"/xunlei/runtime/status"' in text


def test_hardening_does_not_add_downloader_or_full_file_upload_path():
    lowered = text.lower()
    for forbidden in (
        "downloadchain(",
        "from app.chain.download",
        "qbittorrent",
        "transmission",
        "aria2",
        "/userres/v1/flash_upload",
        "content-range",
    ):
        assert forbidden not in lowered
