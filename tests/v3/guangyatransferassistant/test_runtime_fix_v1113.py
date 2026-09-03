from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "runtime_fix_v1113.py"
GOV = PLUGIN / "governance_v1114.py"
FINAL = PLUGIN / "xunlei_final_v1114.py"
UI = PLUGIN / "gying_ui_v1109.py"

patch = PATCH.read_text(encoding="utf-8")
gov = GOV.read_text(encoding="utf-8")
final = FINAL.read_text(encoding="utf-8")
ui = UI.read_text(encoding="utf-8")


def test_runtime_fix_parses_and_is_retained_in_final_gying_chain():
    for path, text in ((PATCH, patch), (GOV, gov), (FINAL, final), (UI, ui)):
        ast.parse(text, filename=str(path))
    assert "class GuangYaRuntimeFixV1113Mixin(GuangYaGyingFallbackReuseV1113Mixin):" in patch
    assert "class GuangYaGovernanceV1114Mixin(GuangYaRuntimeFixV1113Mixin):" in gov
    assert "class GuangYaXunleiFinalV1114Mixin(GuangYaGovernanceV1114Mixin):" in final
    assert "class GuangYaGyingUiV1109Mixin(GuangYaConsoleControlCursorV1116Mixin):" in ui


def test_xunlei_invalid_captcha_chinese_error_forces_one_refresh_without_init_json_gate():
    method = patch.split("    def _xunlei_get(", 1)[1].split("    def _notify_acquisition_v1113", 1)[0]
    detector = patch.split("    def _xunlei_captcha_invalid_v1113", 1)[1].split("    def _xunlei_device_params_v1113", 1)[0]
    assert "验证码" in patch
    assert "无效|失效|错误|过期" in patch
    assert "_CAPTCHA_INVALID_RE_V1113" in detector
    assert "for attempt in range(2)" in method
    assert 'self._xunlei_runtime_captcha_token = ""' in method
    assert "self._refresh_xunlei_captcha(action)" in method
    assert "刷新运行时验证并仅重试当前分享一次" in method
    assert "_xunlei_captcha_init_json" not in method


def test_xunlei_success_notification_counts_only_new_completed_rows():
    method = patch.split("    def _dispatch_xunlei_flash(", 1)[1].split("    def _notify_cloud_completed_v1113", 1)[0]
    assert "before_completed" in method
    assert "key not in before_completed" in method
    assert 'str(row.get("state") or "") == "completed"' in method
    assert '"⚡ 光鸭秒传成功"' in method
    assert "本次成功" in method
    assert "覆盖集数" in method


def test_cloud_notification_is_completion_only_and_persistently_deduped():
    method = patch.split("    def _notify_cloud_completed_v1113(", 1)[1].split("    def _submit_offline_source", 1)[0]
    assert 'str(current.get("state") or "") != "completed"' in method
    assert 'source_type not in {"magnet", "ed2k"}' in method
    assert "completion_notified_at" in method
    assert '"☁️ 光鸭云添加完成"' in method
    assert "self._update_source(source_id, completion_notified_at=self._now_text())" in method
    assert "task_id" in method


def test_notifications_do_not_log_or_render_secret_source_uris():
    lowered = patch.lower()
    assert "magnet:?" not in lowered
    assert "ed2k://" not in lowered
    notify = patch.split("    def _notify_acquisition_v1113", 1)[1]
    for secret in ("captcha_token=", "device_id=", "viewing_password", "viewing_cookie"):
        assert secret not in notify
