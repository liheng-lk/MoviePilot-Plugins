from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
OBS = PLUGIN / "gying_observability_v1104.py"

entry_text = ENTRY.read_text(encoding="utf-8")
text = OBS.read_text(encoding="utf-8")


def test_observability_layer_parses_and_wraps_final_runtime():
    ast.parse(text, filename=str(OBS))
    ast.parse(entry_text, filename=str(ENTRY))
    assert "from .gying_observability_v1104 import GuangYaGyingObservabilityV1104Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant")
    assert entry_text.index("GuangYaGyingObservabilityV1104Mixin,", start) < entry_text.index("GuangYaChannelUiV1101Mixin,", start)
    assert entry_text.index("GuangYaGyingObservabilityV1104Mixin,", start) < entry_text.index("GuangYaGyingHardeningMixin,", start)
    assert 'plugin_version = "1.12.8"' in entry_text
    assert 'build_id = "20260905-r54"' in entry_text


def test_observability_covers_all_real_gying_stages():
    for token in ("运行时初始化", "节点刷新完成", "检测到浏览器 PoW", "PoW通过", "登录检查", "登录结果", "会话结果", "搜索开始", "搜索结果", "downurl成功", "候选提取：Magnet", "迅雷召回", "迅雷执行", "人工操作：测试观影会话", "viewing_observability_state"):
        assert token in text


def test_console_gets_explicit_viewing_test_action():
    assert '"测试观影"' in text
    assert '"/viewing/session/test"' in text
    assert '"刷新观影节点"' in text
    assert "_inject_viewing_test_button" in text


def test_observability_logs_do_not_pass_secret_values():
    tree = ast.parse(text, filename=str(OBS))
    lines = text.splitlines()
    forbidden = ("_viewing_cookie", "_viewing_password", "captcha_token", "passcode", "challenge_id")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "_gying_obs_log"):
            continue
        segment = "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
        for token in forbidden:
            assert token not in segment


def test_observability_is_non_destructive():
    lowered = text.lower()
    for forbidden in ("create_transfer", "flash_upload", "create_task", "add_download", "downloadchain(", "qbittorrent", "transmission", "aria2"):
        assert forbidden not in lowered
