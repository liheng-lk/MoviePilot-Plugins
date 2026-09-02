from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
RUNTIME = PLUGIN / "runtime_fix_v1113.py"
TEXT = RUNTIME.read_text(encoding="utf-8")


def test_runtime_fix_parses_and_keeps_xunlei_device_query_contract():
    ast.parse(TEXT, filename=str(RUNTIME))
    method = TEXT.split("    def _xunlei_device_params_v1113(", 1)[1].split(
        "    def _xunlei_get(", 1
    )[0]
    assert 'output.setdefault("device_id", device_id)' in method
    assert 'output.setdefault("did", device_id)' in method
    assert 'output.setdefault("guid", device_id)' in method
    get_method = TEXT.split("    def _xunlei_get(", 1)[1].split(
        "    def _notify_acquisition_v1113(", 1
    )[0]
    assert "request_params = self._xunlei_device_params_v1113(params)" in get_method
    assert "params=request_params" in get_method


def test_captcha_invalid_supports_chinese_and_opens_batch_circuit_after_one_retry():
    assert "验证码" in TEXT
    assert "error_details" in TEXT
    get_method = TEXT.split("    def _xunlei_get(", 1)[1].split(
        "    def _notify_acquisition_v1113(", 1
    )[0]
    assert '_xunlei_captcha_circuit_open_v1113' in get_method
    assert '_xunlei_captcha_refresh_used_v1113' in get_method
    assert "for attempt in range(2):" in get_method
    assert "本轮已熔断迅雷分享接口" in get_method
    assert "刷新运行时验证并仅重试当前分享一次" in get_method


def test_each_xunlei_dispatch_resets_circuit_and_notifications_remain_enabled():
    dispatch = TEXT.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _notify_cloud_completed_v1113(", 1
    )[0]
    assert "self._xunlei_captcha_circuit_open_v1113 = False" in dispatch
    assert "self._xunlei_captcha_refresh_used_v1113 = False" in dispatch
    assert 'result["captcha_circuit_open"]' in dispatch
    assert "⚡ 光鸭秒传成功" in dispatch
    assert "☁️ 光鸭云添加完成" in TEXT
