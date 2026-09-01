from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_legacy_queue_cleanup_v343.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v343_legacy_queue_recheck_survives_without_running_on_every_init():
    assert "legacy_before = self._legacy_global_queue_snapshot()" in PATCH
    assert "_cleanup_legacy_global_tasks(self)" in PATCH
    assert "_V362_RECHECK_SECONDS = 60.0" in PATCH
    assert "if checked and now_mono < next_recheck:" in PATCH
    assert "每次初始化都会重新检查" not in PATCH


def test_v365_uses_moviepilot_supported_transferpending_compat_abi():
    assert "from app.db.transferpending_oper import TransferPendingOper" in PATCH
    assert "TransferPendingOper()" in PATCH
    assert "app.application.chain.data" not in PATCH


def test_waiting_legacy_tasks_are_removed_with_public_moviepilot_api():
    assert 'remove = state == "waiting"' in PATCH
    assert "chain.remove_from_queue(fileitem)" in PATCH
    assert "pending_oper.discard(storage=storage, src_path=path)" in PATCH
    assert "global_vars.stop_transfer(path)" in PATCH


def test_running_task_uses_history_or_missing_source_terminal_evidence():
    assert "_history_confirms_completed" in PATCH
    assert '== "completed"' in PATCH
    assert "stale_completed = _history_confirms_completed" in PATCH
    assert "stale_missing_source = _legacy_source_missing(self, path)" in PATCH
    assert "removed_missing_source.append(path)" in PATCH
    assert "_drop_missing_source_state(self, path)" in PATCH
    assert "retained_running.append(path)" in PATCH


def test_v366_missing_source_probe_is_tristate_and_network_failures_are_not_missing():
    start = PATCH.index("def _legacy_source_presence")
    end = PATCH.index("def _drop_missing_source_state", start)
    probe = PATCH[start:end]
    assert "client.get_file_list(" in probe
    assert 'response.get("code", -1) != 0' in probe
    assert "return None" in probe
    assert "return False" in probe
    assert "_legacy_source_presence(self, path) is False" in probe
    assert "get_item(" not in probe
    assert "mark_completed" not in probe

    drop_start = PATCH.index("def _drop_missing_source_state")
    drop_end = PATCH.index("def _isolated_runtime_active", drop_start)
    drop = PATCH[drop_start:drop_end]
    for bucket in ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry"):
        assert f'"{bucket}"' in drop
    assert "mark_completed" not in drop


def test_v366_missing_source_cleanup_only_removes_queue_shell_not_remote_media():
    assert "只移除队列壳，不删除远端媒体" in PATCH
    cleanup_start = PATCH.index("def _cleanup_legacy_global_tasks")
    cleanup_end = PATCH.index("def _maybe_log_retained", cleanup_start)
    cleanup = PATCH[cleanup_start:cleanup_end]
    assert "chain.remove_from_queue(fileitem)" in cleanup
    assert "global_vars.stop_transfer(path)" in cleanup
    assert ".delete(" not in cleanup
    assert "delete_file(" not in cleanup
    assert "move_item(" not in cleanup


def _load_presence_helpers():
    tree = ast.parse(PATCH)
    wanted = {"_legacy_source_presence", "_legacy_source_missing"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {
        "Path": Path,
        "Any": Any,
        "Dict": Dict,
        "logger": type("_Logger", (), {"debug": staticmethod(lambda *args, **kwargs: None)})(),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<cleanup-probe>", "exec"), namespace)
    return namespace["_legacy_source_presence"], namespace["_legacy_source_missing"]


class _ProbeClient:
    def __init__(self, mode: str):
        self.mode = mode

    def get_file_list(self, *, parent_id, page_size, order_by, sort_type, file_types, page):
        if self.mode == "error":
            return {"code": -1, "msg": "error", "error": "network"}
        if parent_id == "":
            return {
                "code": 0,
                "msg": "success",
                "data": {"list": [{"fileName": "root", "fileId": "dir-1"}], "total": 1},
            }
        if parent_id == "dir-1" and self.mode == "exists":
            return {
                "code": 0,
                "msg": "success",
                "data": {"list": [{"fileName": "a.mkv", "fileId": "file-1"}], "total": 1},
            }
        return {"code": 0, "msg": "success", "data": {"list": [], "total": 0}}


class _ProbeApi:
    _page_size = 100
    _order_by = 3
    _sort_type = 1

    def __init__(self, mode: str):
        self.client = _ProbeClient(mode)


class _ProbePlugin:
    def __init__(self, mode: str):
        self._guangya_api = _ProbeApi(mode)

    @staticmethod
    def _organize_normalize_path(path: str) -> str:
        return path


def test_v366_presence_probe_distinguishes_missing_from_network_failure():
    presence, missing = _load_presence_helpers()
    assert presence(_ProbePlugin("exists"), "/root/a.mkv") is True
    assert presence(_ProbePlugin("missing"), "/root/a.mkv") is False
    assert presence(_ProbePlugin("error"), "/root/a.mkv") is None
    assert missing(_ProbePlugin("missing"), "/root/a.mkv") is True
    assert missing(_ProbePlugin("error"), "/root/a.mkv") is False


def test_cleanup_is_scoped_to_guangya_storage_and_monitor_path():
    assert "storage not in storage_names" in PATCH
    assert "not self._queue_guard_path_matches(path)" in PATCH
    assert "其它存储未处理" in PATCH


def test_v343_patch_is_installed():
    assert "install_legacy_queue_cleanup_v343" in FILTER
    assert "install_legacy_queue_cleanup_v343()" in FILTER
