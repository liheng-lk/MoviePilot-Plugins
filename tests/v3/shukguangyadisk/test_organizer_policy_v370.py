from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_policy.py"


def _policy():
    spec = importlib.util.spec_from_file_location("shuk_policy_v370_test", POLICY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_present_unrecognized_source_is_left_untouched_not_retry():
    p = _policy()
    assert (
        p.decide_failed_execution(
            "E01.mkv 没有找到可整理的媒体文件",
            p.SourcePresence.PRESENT,
        )
        == p.FileDisposition.LEAVE_UNRECOGNIZED
    )


def test_unknown_presence_never_turns_network_uncertainty_into_unrecognized_terminal():
    p = _policy()
    assert (
        p.decide_failed_execution(
            "E01.mkv 没有找到可整理的媒体文件",
            p.SourcePresence.UNKNOWN,
        )
        == p.FileDisposition.RETRY_TRANSIENT
    )
    assert p.is_unrecognized_message("安全识别已停止整理：MoviePilot 目录标题识别异常：timeout") is False


def test_missing_source_is_retired_not_completed_or_retried():
    p = _policy()
    assert (
        p.decide_failed_execution("目录或文件不存在", p.SourcePresence.MISSING)
        == p.FileDisposition.RETIRE_MISSING
    )


def test_equal_known_byte_size_is_duplicate_delete():
    p = _policy()
    assert p.decide_existing_target(123456789, 123456789) == p.FileDisposition.DELETE_DUPLICATE


def test_different_known_byte_size_is_multi_version_not_duplicate():
    p = _policy()
    assert p.decide_existing_target(123456789, 987654321) == p.FileDisposition.ORGANIZE_VERSION


def test_unknown_size_can_never_authorize_delete():
    p = _policy()
    assert p.decide_existing_target(None, 987654321) == p.FileDisposition.BLOCK_SAFETY
    assert p.decide_existing_target(123456789, None) == p.FileDisposition.BLOCK_SAFETY
