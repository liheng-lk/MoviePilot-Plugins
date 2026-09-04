from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v352.js").read_text(encoding="utf-8")
FAIRNESS = (PLUGIN / "organizer_pending_fairness_v3615.py").read_text(encoding="utf-8")


def test_v3616_status_cards_expose_retry_total_wait_due_and_attempts():
    for token in (
        "state_retry_total",
        "state_retry_wait",
        "state_retry_due",
        "state_retry_max_attempts",
        "'重试总数'",
        "'退避中'",
        "'已到期'",
        "'最大尝试'",
        "已到期待重试",
    ):
        assert token in PAGE, token


def test_v3616_selfcheck_reports_same_retry_time_semantics():
    assert "重试总数 ${rtotal}" in PAGE
    assert "退避中 ${rwait}" in PAGE
    assert "已到期 ${rdue}" in PAGE
    assert "最大尝试 ${rmax}" in PAGE
    # 后端来源必须仍是 v3.6.15 的 retry_at 时间拆分，不在前端重新猜测。
    assert '"retry_total": len(retry)' in FAIRNESS
    assert '"retry_wait": waiting' in FAIRNESS
    assert '"retry_due": due' in FAIRNESS
    assert '"retry_max_attempts": max_attempts' in FAIRNESS


def test_v3616_removes_obsolete_sticky_ui_copy_after_v360_engine_removed_sticky():
    for obsolete in (
        "目录粘性事务",
        "当前目录收口前不切换其它剧集",
        "sticky_tv_group_path",
        "该目录未完成前不会切换到其它剧集",
    ):
        assert obsolete not in PAGE, obsolete
    assert "单 Worker 串行执行" in PAGE
    assert "等待资源优先复查" in PAGE
    assert "同一监控周期继续发现新资源" in PAGE


def test_v3616_ui_is_observability_only_and_keeps_moviepilot_business_boundary():
    for forbidden in (
        "target_directory",
        "rename_format",
        "MediaType.TV",
        "MediaType.MOVIE",
        "planning_input",
        "TransferExecutionCommand",
        "move_item(",
        "delete_file(",
        "overwrite_mode",
    ):
        assert forbidden not in PAGE, forbidden
    assert "整理规则：MoviePilot 内置" in PAGE
    assert "目标目录、分类、重命名、覆盖、刮削和媒体整理历史仍由 MoviePilot 产生" in PAGE


def test_v3616_keeps_old_backend_compatibility_when_new_retry_fields_are_missing():
    # 旧后端没有 state_retry_total 时，总数退回旧 state_retry_wait/retry_wait；新字段则优先。
    assert "state_retry_total??status.value?.state_retry_wait??status.value?.retry_wait" in PAGE
    assert "c.state_retry_total??c.state_retry_wait" in PAGE


def test_v3616_does_not_add_internal_version_badges():
    assert "gya-badge" not in PAGE
    assert "gy-version" not in PAGE
    assert "v3.6.16" not in PAGE
