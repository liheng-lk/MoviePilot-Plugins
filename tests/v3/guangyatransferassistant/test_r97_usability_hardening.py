from __future__ import annotations

import ast
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[3]
MULTI = ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py"
LEGACY = ROOT / "plugins.v3" / "guangyatransferassistant" / "legacy.py"
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



def _pending_verify_mixin():
    source = LEGACY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(LEGACY))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaTransferAssistant"
    )
    wanted = {"_pending_job_verify_items", "_recheck_pending_only"}
    methods = [
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    module = ast.Module(
        body=[ast.ClassDef(
            name="PendingVerifyProbe",
            bases=[],
            keywords=[],
            body=methods,
            decorator_list=[],
        )],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Path": Path,
        "_safe_relative_path": lambda value: str(value or "").replace("\\", "/").strip("/"),
    }
    exec(compile(module, str(LEGACY), "exec"), ns)
    return ns["PendingVerifyProbe"]


def _pending_verify_harness(*, verify_success: bool, with_pending: bool = True):
    mixin = _pending_verify_mixin()

    class Sub:
        id = 88
        name = "测试剧"
        season = 1
        type = "TV"

    class Harness(mixin):
        def __init__(self):
            self.jobs = {
                "job-1": {
                    "subscribe_id": 88,
                    "media": "tv:88",
                    "status": "verifying",
                    "target": "/media/测试剧 (2026)",
                    "paths": ["Season 1/测试剧.S01E05.2160p.WEB-DL.mkv"],
                }
            } if with_pending else {}
            self.verify_success = verify_success
            self.verify_calls = 0
            self.job_updates = []
            self.fact_calls = 0
            self.progress_calls = 0
            self.library_calls = 0
            self.finish_calls = 0
            self.logs = []
            self.search_calls = 0
            self.restore_calls = 0

        def _pending_jobs_for_subscription(self, _subscribe):
            return [(key, dict(value)) for key, value in self.jobs.items()]

        def _target_path(self, _subscribe):
            return "/media/测试剧 (2026)"

        def _verify_restored_items(self, target, items, max_try=1):
            self.verify_calls += 1
            assert target == "/media/测试剧 (2026)"
            assert max_try == 1
            if self.verify_success:
                return {"success": True, "verified_items": list(items)}
            return {"success": False, "message": "目标文件尚未出现", "verified_items": []}

        def _set_job_state(self, key, status, **fields):
            self.job_updates.append((key, status, dict(fields)))
            if key in self.jobs:
                self.jobs[key].update(fields)
                self.jobs[key]["status"] = status

        def _remember_media_facts(self, _subscribe, items, origin="transfer"):
            self.fact_calls += 1
            assert origin == "pending_recheck"
            return len(items)

        def _sync_progress(self, _subscribe, _items):
            self.progress_calls += 1

        def _sync_media_library_progress(self, _subscribe):
            self.library_calls += 1
            return {"success": True, "existing": [5], "missing": []}

        def _finish_subscription_if_complete(self, _subscribe):
            self.finish_calls += 1
            return True

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message, args))

        # 这些调用若出现，就说明 verify-only 泄漏进资源获取链。
        def refresh_channels(self, *args, **kwargs):
            self.search_calls += 1
            raise AssertionError("verify-only must not refresh channel")

        def _dispatch_viewing_external_v1113(self, *args, **kwargs):
            self.search_calls += 1
            raise AssertionError("verify-only must not search GYING")

        def _restore_items(self, *args, **kwargs):
            self.restore_calls += 1
            raise AssertionError("verify-only must not create transfer")

    return Harness(), Sub()


def test_pending_recheck_without_pending_job_is_true_noop():
    h, sub = _pending_verify_harness(verify_success=False, with_pending=False)
    out = h._recheck_pending_only(sub)
    assert out["success"] is True
    assert out["verify_only"] is True
    assert out["pending"] == 0
    assert h.verify_calls == 0
    assert h.search_calls == 0
    assert h.restore_calls == 0


def test_pending_recheck_missing_file_keeps_verifying_without_new_search_or_transfer():
    h, sub = _pending_verify_harness(verify_success=False)
    out = h._recheck_pending_only(sub)
    assert out["success"] is False
    assert out["verify_only"] is True
    assert out["verified"] == 0
    assert out["pending"] == 1
    assert h.job_updates[-1][1] == "verifying"
    assert h.fact_calls == 0
    assert h.progress_calls == 0
    assert h.search_calls == 0
    assert h.restore_calls == 0


def test_pending_recheck_visible_file_only_syncs_facts_and_completion():
    h, sub = _pending_verify_harness(verify_success=True)
    out = h._recheck_pending_only(sub)
    assert out["success"] is True
    assert out["verify_only"] is True
    assert out["verified"] == 1
    assert out["pending"] == 0
    assert h.job_updates[-1][1] == "verified"
    assert h.fact_calls == 1
    assert h.progress_calls == 1
    assert h.library_calls == 1
    assert h.finish_calls == 1
    assert h.search_calls == 0
    assert h.restore_calls == 0



def _landing_snapshot_harness(sync_result):
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self.source = {"id": "src-land"}
            self.sync_result = sync_result
            self.logs = []

        def _sync_media_library_progress(self, _subscribe):
            if isinstance(self.sync_result, Exception):
                raise self.sync_result
            return dict(self.sync_result)

        def _update_source(self, _source_id, **fields):
            self.source.update(fields)
            return dict(self.source)

        @staticmethod
        def _now_text():
            return "2026-09-12 12:00:00"

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message, args))

    return Harness()


def test_remote_confirmed_target_stays_library_pending_until_all_target_episodes_are_observed():
    h = _landing_snapshot_harness({"success": True, "existing": [5]})
    source = {"id": "src-land", "target_episodes": [5, 6]}
    out = h._record_library_landing_snapshot_v180(source, _Sub(), {"state": "completed"})

    assert out["library_snapshot_state"] == "pending"
    assert out["library_observed_episodes"] == [5]
    assert out["library_remaining_target_episodes"] == [6]
    assert out["landing_stage"] == "LIBRARY_PENDING"
    assert out["remote_confirmed_at"] == "2026-09-12 12:00:00"


def test_remote_confirmed_target_becomes_library_confirmed_only_after_all_target_episodes_exist():
    h = _landing_snapshot_harness({"success": True, "existing": [1, 5, 6, 99]})
    source = {"id": "src-land", "resolved_episodes": [5, 6]}
    out = h._record_library_landing_snapshot_v180(source, _Sub(), {"state": "completed"})

    assert out["library_snapshot_state"] == "confirmed"
    assert out["library_observed_episodes"] == [5, 6]
    assert out["library_remaining_target_episodes"] == []
    assert out["landing_stage"] == "LIBRARY_CONFIRMED"


def test_remote_confirmed_movie_or_unscoped_source_is_checked_not_falsely_episode_confirmed():
    h = _landing_snapshot_harness({"success": True, "existing": [5]})
    source = {"id": "src-land", "target_episodes": []}
    out = h._record_library_landing_snapshot_v180(source, _Sub(), {"state": "completed"})

    assert out["library_snapshot_state"] == "checked"
    assert out["library_observed_episodes"] == []
    assert out["library_remaining_target_episodes"] == []
    assert out["landing_stage"] == "LIBRARY_CHECKED"


def test_library_snapshot_failure_is_unknown_and_never_rewrites_source_success_semantics():
    h = _landing_snapshot_harness(RuntimeError("Emby unavailable"))
    source = {"id": "src-land", "target_episodes": [5]}
    out = h._record_library_landing_snapshot_v180(
        source,
        _Sub(),
        {
            "state": "completed",
            "remote_video_confirmed": True,
            "remote_verify_source": "task_result_filename",
        },
    )

    assert out["state"] == "completed"
    assert out["remote_video_confirmed"] is True
    assert out["remote_verify_source"] == "task_result_filename"
    assert out["library_snapshot_state"] == "unknown"
    assert out["landing_stage"] == "LIBRARY_UNKNOWN"
    assert "Emby unavailable" in out["library_snapshot_error"]
