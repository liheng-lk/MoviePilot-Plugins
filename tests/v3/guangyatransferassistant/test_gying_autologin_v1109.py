from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
AUTO = PLUGIN / "gying_autologin_v1109.py"
TRANSPORT = PLUGIN / "gying_transport_v1108.py"
AUTH = PLUGIN / "gying_auth_v1107.py"
ENTRY = PLUGIN / "__init__.py"

auto_text = AUTO.read_text(encoding="utf-8")
transport_text = TRANSPORT.read_text(encoding="utf-8")
auth_text = AUTH.read_text(encoding="utf-8")
entry_text = ENTRY.read_text(encoding="utf-8")

def test_v1109_files_parse_and_release_metadata_are_aligned():
    for path, text in ((AUTO, auto_text), (TRANSPORT, transport_text), (AUTH, auth_text), (ENTRY, entry_text)):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.12.11"
    assert 'plugin_version = "1.12.11"' in entry_text
    assert 'build_id = "20260905-r57"' in entry_text
    assert "v1.12.5" in package.get("history", {})
    assert "v1.12.3" in package.get("history", {})
    assert "v1.10.13" in package.get("history", {})
    assert "v1.10.12" in package.get("history", {})
    assert "v1.10.10" in package.get("history", {})
    assert "v1.10.9" in package.get("history", {})

def test_auto_login_is_outermost_before_transport_and_old_auth_layers():
    assert "from .gying_autologin_v1109 import GuangYaGyingAutoLoginV1109Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaGyingAutoLoginV1109Mixin,", start) < entry_text.index("GuangYaGyingTransportV1108Mixin,", start)
    assert entry_text.index("GuangYaGyingTransportV1108Mixin,", start) < entry_text.index("GuangYaStabilityV1106Mixin,", start)

def test_password_login_uses_empty_code_before_any_manual_captcha():
    login = auto_text.split("    def _gying_login_password(", 1)[1].split("    # ------------------------------------------------------------------\n    # 点击", 1)[0]
    assert '"code": ""' in login
    assert '"siteid": "1"' in login
    assert '"dosubmit": "1"' in login
    assert '"cookietime": "10506240"' in login
    assert '"username": username' in login
    assert '"password": password' in login
    assert 'node.rstrip("/") + "/user/login"' in login
    assert 'node.rstrip("/") + "/mv/wkMn"' in login
    assert "self._gying_authenticated_probe(session, node)" in login

def test_manual_captcha_is_only_server_requested_fallback():
    assert '_contains_hint_v1109(message, _CAPTCHA_HINTS_V1109)' in auto_text
    assert '"mode": "captcha_required"' in auto_text
    worker = auto_text.split("    def _gying_auth_worker_run_v1108(", 1)[1]
    assert "self._gying_login_password(session, node)" in worker
    assert 'if mode != "captcha_required":' in worker
    assert "captcha = self._gying_request_captcha(session, node)" in worker
    assert worker.index("self._gying_login_password(session, node)") < worker.index("self._gying_request_captcha(session, node)")

def test_manual_captcha_is_not_automatically_solved():
    lowered = "\n".join((auto_text, auth_text)).lower()
    for forbidden in ("pytesseract", "easyocr", "paddleocr", "captcha_solver"):
        assert forbidden not in lowered
    assert "不会自动识别" in auth_text or "不会自动识别" in auto_text

def test_start_api_converts_internal_exception_to_structured_json():
    method = auto_text.split("    def api_viewing_auth_start(", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "try:" in method
    assert "except Exception as err:" in method
    assert '"stage": "error"' in method
    assert "type(err).__name__" in method
    assert "password" not in method.lower()
    assert "cookie" not in method.lower()

def test_fixed_route_priority_and_native_cloudcollection_are_untouched():
    assert "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in entry_text
    assert "Magnet/ED2K 继续使用光鸭原生 cloudcollection" in entry_text
