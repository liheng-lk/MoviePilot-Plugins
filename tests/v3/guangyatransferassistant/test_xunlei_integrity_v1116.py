from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
INTEGRITY = PLUGIN / "xunlei_integrity_v1116.py"
LOGGING = PLUGIN / "viewing_logging_v1113.py"
XUNLEI = PLUGIN / "xunlei_flash_v193.py"

integrity = INTEGRITY.read_text(encoding="utf-8")
logging = LOGGING.read_text(encoding="utf-8")
xunlei = XUNLEI.read_text(encoding="utf-8")


def test_integrity_layer_parses_and_is_between_viewing_dispatch_and_legacy_xunlei():
    ast.parse(integrity, filename=str(INTEGRITY))
    ast.parse(logging, filename=str(LOGGING))
    assert "from .xunlei_integrity_v1116 import GuangYaXunleiIntegrityV1116Mixin" in logging
    assert "GuangYaViewingDispatchV1113Mixin,\n    GuangYaXunleiIntegrityV1116Mixin," in logging
    assert 'build_id = "20260902-r28"' in logging


def test_fileid_alone_is_not_a_success_signal_anymore():
    poll = integrity.split("    def _xunlei_poll_task_integrity_v1116(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 严格秒传", 1
    )[0]
    assert "observed_size == int(expected_size or 0)" in poll
    assert "observed_size > 0" in poll
    assert "_xunlei_find_exact_file_v1116(parent_id, name, expected_size)" in poll
    assert "if file_id:" in poll
    assert "return True" not in poll


def test_instant_code_156_must_be_verified_by_exact_remote_size():
    rapid = integrity.split("    def _rapid_transfer_xunlei_file(", 1)[1].split(
        "    def _dispatch_xunlei_flash(", 1
    )[0]
    assert 'code in (156, "156")' in rapid
    assert "_xunlei_wait_exact_file_v1116(" in rapid
    assert "目标目录未确认到同名同大小文件" in rapid
    assert "verified_size" in rapid


def test_missing_real_cid_never_calls_check_and_cleans_upload_task():
    rapid = integrity.split("    def _rapid_transfer_xunlei_file(", 1)[1].split(
        "    def _dispatch_xunlei_flash(", 1
    )[0]
    guard = rapid.split("if not cid_candidates:", 1)[1].split("accepted_task =", 1)[0]
    assert "_xunlei_cleanup_placeholders_v1116" in guard
    assert "缺少真实 CID" in guard
    assert "check_can_flash_upload" not in guard


def test_failed_flash_cleans_only_new_same_name_bad_size_placeholders():
    cleanup = integrity.split("    def _xunlei_cleanup_placeholders_v1116(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # task 最终完成", 1
    )[0]
    assert "file_id in before" in cleanup
    assert "row_name != name" in cleanup
    assert "row_size <= 0 or row_size != int(expected_size or 0)" in cleanup
    assert '"/userres/v1/file/delete_upload_task"' in integrity
    assert '"/userres/v1/file/delete_file"' in integrity


def test_same_content_probe_is_deduped_within_one_xunlei_batch():
    assert '_xunlei_flash_integrity_seen_v1116 = set()' in integrity
    assert 'dedupe_key = f"{gcid}:{size}:{cid_candidates[0] if cid_candidates else \'-\'}"' in integrity
    assert "同批次相同 GCID/size/CID 已探测" in integrity


def test_old_fileid_only_poll_remains_below_new_override_not_used_directly():
    # 保留旧实现便于兼容/回滚，但最终 ViewingDispatch.super() 必须先命中新 integrity mixin。
    assert "def _poll_guangya_flash_task" in xunlei
    assert "GuangYaXunleiIntegrityV1116Mixin" in logging
