import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PAGE_AUTH = PLUGIN / "page_auth_v172.py"
TEXT = PAGE_AUTH.read_text(encoding="utf-8")


def test_page_resilience_module_parses():
    ast.parse(TEXT, filename=str(PAGE_AUTH))


def test_page_resilience_guards_all_page_failure_boundaries():
    for token in (
        "_install_page_resilience_v1102",
        "_fallback_overview",
        "_page_fallback_cards",
        "safe_overview",
        "safe_health",
        "safe_channel_card",
        "safe_console_page",
        "safe_channel_page",
        "_status_overview_v191",
        "_runtime_health_rows",
        "_channel_page_card_v1101",
    ):
        assert token in TEXT


def test_page_resilience_never_exposes_exception_text_in_ui_alerts():
    # 详细异常只进插件日志；页面只显示阶段名称，避免 Provider URL/Cookie 等异常上下文泄露。
    assert "【页面降级】%s 读取失败，已隔离该模块：%s" in TEXT
    assert '"text": "已隔离：" + "、".join(errors[:6])' in TEXT
    assert "f\"后台任务提交失败：{err}\"" in TEXT  # 旧 API 行为仍保留，非页面加载告警。


def test_page_resilience_keeps_background_transfer_semantics_untouched():
    # 本补丁只能包页面只读方法，不得改转存/云添加入口。
    forbidden = (
        "create_transfer(",
        "flash_upload(",
        "resolve_res(",
        "create_task(",
        "add_download(",
    )
    resilience = TEXT.split("# v1.10.2 页面数据故障隔离", 1)[1]
    for token in forbidden:
        assert token not in resilience
