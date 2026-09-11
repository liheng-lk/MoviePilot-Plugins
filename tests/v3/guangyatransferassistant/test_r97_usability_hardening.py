from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[3]
MULTI = ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py"
SOURCE = MULTI.read_text(encoding="utf-8")
STATUS = (ROOT / "plugins.v3" / "guangyatransferassistant" / "status_ui_v191.py").read_text(encoding="utf-8")


def _mixin_class():
    tree = ast.parse(SOURCE, filename=str(MULTI))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaMultiSourceMixin"
    )
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "Iterable": __import__("typing").Iterable,
        "Path": Path,
        "threading": threading,
        "time": time,
        "SOURCE_PENDING_STATES": {"new", "retry"},
        "SOURCE_INFLIGHT_STATES": {"dispatching", "submitted", "queued", "waiting"},
        "normalize_source_uri": lambda uri: {
            "type": "magnet",
            "uri": uri,
            "identity": "x",
            "name": "",
            "size": 0,
        },
        "_is_video": lambda name: str(name or "").lower().endswith((".mkv", ".mp4", ".ts")),
        "_is_subtitle": lambda name: str(name or "").lower().endswith((".srt", ".ass", ".ssa")),
        "_episode_numbers": lambda _name: (0, []),
        "_normalize_media_text": lambda value: str(value or "").strip().lower(),
        "GuangYaSourceStoreMixin": type("Base", (), {}),
    }
    exec(compile(module, str(MULTI), "exec"), ns)
    return ns["GuangYaMultiSourceMixin"]


class _Sub:
    id = 77
    season = 1
    name = "测试剧"


def _poll_harness(*, existing, pending_verify_since=0.0, grace=1200):
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self._offline_remote_verify_grace_seconds = grace
            self.source = {
                "id": "src-1",
                "subscribe_id": 77,
                "type": "magnet",
                "state": "waiting",
                "task_id": "TASK-1",
                "target_episodes": [5],
                "resolved_episodes": [5],
                "selected_manifest": [{"name": "S01E05.mkv", "type": "video"}],
                "pending_verify_since": pending_verify_since,
                "enabled": True,
                "auto_dispatch": True,
            }
            self.diags = []
            self.health = {}
            self.logs = []

        def _offline_request(self, _endpoint, _payload):
            return {}

        def _offline_api_success(self, _response):
            return True

        def _offline_task_rows(self, _response):
            # 光鸭服务端明确 completed，但没有返回可用于正片验真的 fileName。
            return [{"taskId": "TASK-1", "status": 2, "progress": 100, "fileId": "F-1", "fileName": ""}]

        def _find_subscription(self, sid):
            return _Sub() if int(sid or 0) == 77 else None

        def _is_movie_subscription(self, _subscribe):
            return False

        def _sync_media_library_progress(self, _subscribe):
            return {"success": True, "existing": list(existing), "missing": []}

        def _update_source(self, _source_id, **fields):
            self.source.update(fields)
            return dict(self.source)

        def _writeback_offline_candidate_diag_v209(self, _source, **fields):
            self.diags.append(dict(fields))

        def _record_route_health(self, **fields):
            self.health.update(fields)

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message, args))

        def _now_text(self):
            return "2026-09-11 21:00:00"

        def _mark_offline_failure(self, source, error, *, attempt_increment=True):
            self.source.update(
                state="retry",
                last_error=str(error),
                attempts=int(self.source.get("attempts") or 0) + (1 if attempt_increment else 0),
            )
            return dict(self.source)

    return Harness()


def test_remote_completed_without_filename_releases_claim_when_library_already_satisfied():
    h = _poll_harness(existing=[5])
    out = h._poll_offline_source(dict(h.source))

    assert out["success"] is True
    assert out["skipped"] is True
    assert out["verified"] is False
    assert out["reason"] == "library_satisfied_unattributed"
    assert h.source["state"] == "disabled"
    assert h.source["enabled"] is False
    assert h.source["remote_video_confirmed"] is False
    assert h.source["remote_verify_source"] == "library_satisfied_unattributed"
    assert "REMOTE_RECEIPT_UNVERIFIED" in h.source["last_error"]
    # 核心不变量：媒体库事实只能停止重复占位，不能伪造来源成功。
    assert not h.source.get("completed_at")
    assert any(row.get("reason_code") == "LIBRARY_ALREADY_SATISFIED" for row in h.diags)


def test_remote_completed_unverified_does_not_wait_forever():
    h = _poll_harness(
        existing=[],
        pending_verify_since=time.time() - 700,
        grace=300,
    )
    out = h._poll_offline_source(dict(h.source))

    assert out["success"] is False
    assert out["reason"] == "remote_verify_timeout"
    assert h.source["state"] == "needs_review"
    assert h.source["remote_video_confirmed"] is False
    assert h.source["remote_verify_source"] == "timeout_unverified"
    assert "REMOTE_VERIFY_TIMEOUT" in h.source["last_error"]
    assert any(row.get("reason_code") == "REMOTE_VERIFY_FAILED" for row in h.diags)


def test_remote_completed_unverified_stays_pending_inside_grace_window():
    h = _poll_harness(
        existing=[],
        pending_verify_since=time.time() - 30,
        grace=300,
    )
    out = h._poll_offline_source(dict(h.source))

    assert out["success"] is False
    assert h.source["state"] == "waiting"
    assert h.source["remote_video_confirmed"] is False
    assert h.source["pending_verify_since"] > 0
    assert "last_offline_pending_verify_at" in h.health
    assert "last_offline_completed_at" not in h.health


def test_daemon_dispatch_exception_is_persisted_and_slot_is_released():
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self._enabled = True
            self._offline_worker_lock = threading.Lock()
            self._offline_worker_ids = set()
            self.source = {
                "id": "src-err",
                "state": "dispatching",
                "enabled": True,
                "task_id": "",
            }
            self.failed = []
            self.logs = []

        def _source_store(self):
            return {"items": {"src-err": self.source}}

        def _submit_offline_source(self, _source_id):
            raise RuntimeError("boom")

        def _mark_offline_failure(self, source, error, *, attempt_increment=True):
            self.failed.append(str(error))
            self.source.update(state="retry", last_error=str(error))
            return dict(self.source)

        def _update_source(self, _source_id, **fields):
            self.source.update(fields)
            return dict(self.source)

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message, args))

    h = Harness()
    result = h._spawn_source_dispatch("src-err")
    assert result["success"] is True

    deadline = time.time() + 2.0
    while time.time() < deadline and "src-err" in h._offline_worker_ids:
        time.sleep(0.01)

    assert "src-err" not in h._offline_worker_ids
    assert h.source["state"] == "retry"
    assert h.failed == ["boom"]
    assert any(level == "EXCEPTION" for level, _, _ in h.logs)


def test_daemon_dispatch_exception_with_existing_task_never_recreates_task():
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self._enabled = True
            self._offline_worker_lock = threading.Lock()
            self._offline_worker_ids = set()
            self.source = {
                "id": "src-task",
                "state": "dispatching",
                "enabled": True,
                "task_id": "TASK-EXISTS",
            }
            self.mark_failure_called = 0
            self.logs = []

        def _source_store(self):
            return {"items": {"src-task": self.source}}

        def _submit_offline_source(self, _source_id):
            raise RuntimeError("worker crash after task creation")

        def _mark_offline_failure(self, source, error, *, attempt_increment=True):
            self.mark_failure_called += 1
            return source

        def _update_source(self, _source_id, **fields):
            self.source.update(fields)
            return dict(self.source)

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message, args))

    h = Harness()
    result = h._spawn_source_dispatch("src-task")
    assert result["success"] is True

    deadline = time.time() + 2.0
    while time.time() < deadline and "src-task" in h._offline_worker_ids:
        time.sleep(0.01)

    assert "src-task" not in h._offline_worker_ids
    assert h.source["task_id"] == "TASK-EXISTS"
    assert h.source["state"] == "waiting"
    assert h.mark_failure_called == 0
    assert "保留 taskId" in h.source["last_error"]


def test_r97_source_contracts_present():
    assert "_offline_remote_verify_grace_seconds = 20 * 60" in SOURCE
    assert "library_satisfied_unattributed" in SOURCE
    assert "REMOTE_VERIFY_TIMEOUT" in SOURCE
    assert "release_claim_for_fallback" in SOURCE
    assert "后台来源执行异常，已进入恢复路径" in SOURCE


def test_r97_status_ui_explains_pending_verify_instead_of_fake_100_percent_progress():
    assert "远端任务已完成，正在核验正片" in STATUS
    assert 'error.startswith("PENDING_VERIFY:")' in STATUS
    assert "pending_verify_since" in STATUS


def test_r97_status_ui_gives_specific_action_for_verify_timeout():
    assert '"REMOTE_VERIFY_TIMEOUT" in error' in STATUS
    assert "先刷新云任务并确认目标目录/媒体库" in STATUS
