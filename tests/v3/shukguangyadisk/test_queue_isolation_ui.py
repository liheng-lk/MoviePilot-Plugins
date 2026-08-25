from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v340.js").read_text(encoding="utf-8")
RECOVERY_PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v341.js").read_text(encoding="utf-8")


def test_preview_remote_entry_loads_queue_recovery_console():
    assert "__federation_expose_AssistantPage-v341.js?v=3.4.0-preview3" in REMOTE
    assert "GuangyaCloudAssistantV341" in RECOVERY_PAGE
    assert "__federation_expose_AssistantPage-v340.js?v=3.4.0-preview3" in RECOVERY_PAGE


def test_ui_separates_scan_batch_and_moviepilot_occupancy():
    for token in (
        "单轮候选处理上限",
        "光鸭 MP 占用上限（1–8）",
        "无最终回执熔断（秒）",
        "当前实际上限",
        "扫描批次与 MP 队列容量完全分离",
    ):
        assert token in PAGE, token
    assert "max_inflight:Number(maxInflight.value||1)" in PAGE
    assert "stall_timeout:Number(stallTimeout.value||900)" in PAGE


def test_ui_explains_one_worker_limitation_and_old_backlog():
    for token in (
        "MoviePilot 当前只有 1 个整理线程",
        "TRANSFER_THREADS 调整为至少 2",
        "检测到旧版本队列积压",
        "不会自动清空 MP 全局队列",
        "队列隔离已生效",
    ):
        assert token in PAGE, token


def test_ui_surfaces_stall_breaker_and_real_dispatch_status():
    for token in (
        "已触发整理熔断",
        "dispatch_host_transfer_threads",
        "dispatch_inflight",
        "dispatch_stalled",
        "dispatch_oldest_age_seconds",
        "queue_slots",
        "pending_group_count",
        "旧队列超额",
    ):
        assert token in PAGE, token


def test_ui_can_recover_moviepilot_native_guangya_backlog_without_touching_other_tasks():
    for token in (
        "MoviePilot 原生整理队列中的光鸭积压",
        "MP 总队列",
        "光鸭",
        "等待",
        "运行",
        "清理旧光鸭排队",
        "终止卡住的光鸭任务",
        "/organize/monitor/recover-queue",
        "confirm:true",
        "monitor_only:true",
        "include_running:includeRunning",
        "不碰运行中任务和其它 MoviePilot 整理",
        "等待约 2 分钟",
    ):
        assert token in RECOVERY_PAGE, token


def test_ui_keeps_folder_group_history_and_moviepilot_business_boundary():
    for token in (
        "按子文件夹整理历史",
        "folder_history",
        "group_path",
        "已完成",
        "整理中",
        "MP 门控",
        "目标目录、重命名、整理方式、覆盖、刮削和最终媒体身份均不在插件中复制",
    ):
        assert token in PAGE, token
