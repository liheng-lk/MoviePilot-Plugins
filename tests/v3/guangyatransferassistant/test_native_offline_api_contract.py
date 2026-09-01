"""锁定光鸭 cloudcollection API 字段/状态映射，防止后续误改成下载器语义。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MULTI = (ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py").read_text(encoding="utf-8")


def test_create_task_persists_guangya_task_id():
    block = MULTI.split("    def _submit_offline_source(", 1)[1].split("    def _retry_offline_task(", 1)[0]
    assert 'data.get("taskId")' in block
    assert 'task_id=task_id' in block
    assert 'state="submitted"' in block
    assert '"parentId": parent_id' in block


def test_native_status_mapping_is_explicit():
    block = MULTI.split("    def _poll_offline_source(", 1)[1].split("    # ------------------------------------------------------------------\n    # 调度与 API", 1)[0]
    assert "if status == 2:" in block
    assert 'state="completed"' in block
    assert "if status == 5:" in block
    assert 'state="retry"' in block
    assert 'state="failed"' in block
    assert 'state = "queued" if status == 0 else "waiting"' in block


def test_resolved_file_indexes_are_forwarded_to_guangya_not_local_downloader():
    select = MULTI.split("    def _select_offline_file_indexes(", 1)[1].split("    def _resolve_offline_source(", 1)[0]
    submit = MULTI.split("    def _submit_offline_source(", 1)[1].split("    def _retry_offline_task(", 1)[0]
    assert "_is_video" in select and "_is_subtitle" in select
    assert "_subscription_missing_episodes" in select
    assert 'payload["fileIndexes"] = resolved["selected_indexes"]' in submit


def test_no_native_downloader_submission_symbols_in_multisource_layer():
    for forbidden in (
        "download_single(",
        "download_torrent(",
        "DownloadChain(",
        "DownloaderHelper(",
        "qbittorrent.",
        "transmission.",
    ):
        assert forbidden not in MULTI, forbidden
