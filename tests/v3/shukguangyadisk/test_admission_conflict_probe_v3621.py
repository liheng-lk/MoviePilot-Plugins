from __future__ import annotations

import ast
import importlib.util
import sys
import threading
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH_PATH = PLUGIN / "organizer_admission_conflict_probe_v3621.py"
PATCH = PATCH_PATH.read_text(encoding="utf-8")


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def _load_module():
    app = sys.modules.setdefault("app", types.ModuleType("app"))
    sdk = sys.modules.setdefault("app.sdk", types.ModuleType("app.sdk"))
    logging_mod = types.ModuleType("app.sdk.logging")
    logging_mod.logger = _Logger()
    sys.modules["app.sdk.logging"] = logging_mod
    setattr(app, "sdk", sdk)
    setattr(sdk, "logging", logging_mod)

    spec = importlib.util.spec_from_file_location("shuk_v3621_probe_test", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TransferAdmissionConflictError(RuntimeError):
    pass


class _Member:
    def __init__(self, path: str):
        self.path = path
        self.name = PureName(path)


def PureName(path: str) -> str:
    return str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


class _Item:
    def __init__(self, members):
        self.members = list(members)
        self.path = "/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1"


class _FakeStore:
    def __init__(self, paths):
        self.inflight = set(paths)
        self.blocked = set()
        self.completed = set()
        self.retry = set()

    def mark_completed(self, *, path, fingerprint):
        self.inflight.discard(path)
        self.retry.discard(path)
        self.blocked.discard(path)
        self.completed.add(path)


class _Plugin:
    _disk_name = "光鸭云盘助手"
    _legacy_disk_name = "Shuk-光鸭云盘"

    def __init__(self, paths):
        self.store = _FakeStore(paths)
        self.status = {}

    @staticmethod
    def _organize_normalize_path(path):
        return str(path or "").replace("\\", "/").rstrip("/") or "/"

    @staticmethod
    def _v360_members(item):
        return list(getattr(item, "members", None) or [item])

    @staticmethod
    def _v360_member_identity(member):
        return str(member.path), f"fp:{member.path}"

    @staticmethod
    def _v360_history_decision(member, path):
        return {"decision": "failed", "history_id": 0, "transfer_task_id": ""}

    def _state(self):
        return self.store

    def _save_monitor_status(self, **kwargs):
        self.status.update(kwargs)


class _FakeRepoBase:
    pass


def _reset_repo_class(repo_cls):
    for name in (
        "_shuk_v3621_admission_probe_wrapped",
        "_shuk_v3621_admission_probe_local",
        "_shuk_v3621_original_admit",
    ):
        if hasattr(repo_cls, name):
            delattr(repo_cls, name)


def test_v3621_source_is_parseable_and_observer_only_at_host_boundary():
    ast.parse(PATCH, filename=str(PATCH_PATH))
    assert "TransactionalTransferAdmissionRepository" in PATCH
    assert "except Exception as err" in PATCH
    assert "raise\n" in PATCH
    assert "repository.admit" not in PATCH
    assert ".discard(storage=" not in PATCH
    assert "delete_file" not in PATCH
    assert "move_item" not in PATCH
    assert "planning_input=" not in PATCH
    assert "request_retry(" not in PATCH


def test_exact_host_admission_conflict_is_recorded_and_re_raised_unchanged():
    module = _load_module()

    error = TransferAdmissionConflictError(
        "整理源文件已按不同输入准入: 光鸭云盘助手:/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/E08.mp4"
    )

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            raise error

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    assert module.install_moviepilot_admission_probe_v3621() is True

    caught = None
    try:
        Repo().admit(
            storage="光鸭云盘助手",
            src_path="/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/E08.mp4",
            planning_input=object(),
        )
    except Exception as err:  # noqa: BLE001
        caught = err

    assert caught is error
    rows = module._records()
    assert len(rows) == 1
    assert rows[0]["storage"] == "光鸭云盘助手"
    assert rows[0]["src_path"].endswith("/E08.mp4")
    assert rows[0]["error_type"] == "TransferAdmissionConflictError"


def test_ordinary_host_failure_is_re_raised_but_never_recorded_as_admission_conflict():
    module = _load_module()

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            raise RuntimeError("temporary database failure")

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    module.install_moviepilot_admission_probe_v3621()

    try:
        Repo().admit(storage="光鸭云盘助手", src_path="/光鸭媒体库/x.mp4", planning_input=object())
    except RuntimeError:
        pass
    else:
        raise AssertionError("ordinary failure must still propagate")

    assert module._records() == []


def test_probe_records_are_thread_local_and_clear_before_next_worker_execution():
    module = _load_module()

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            return object()

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    module.install_moviepilot_admission_probe_v3621()
    module._remember_conflict(
        storage="光鸭云盘助手",
        src_path="/光鸭媒体库/a.mp4",
        error=TransferAdmissionConflictError("TransferAdmissionConflictError"),
    )
    assert len(module._records()) == 1

    seen = []

    def read_other_thread():
        seen.extend(module._records())

    thread = threading.Thread(target=read_other_thread)
    thread.start()
    thread.join()
    assert seen == []

    module.clear_admission_probe_v3621()
    assert module._records() == []


def test_real_datang_two_conflicts_hidden_by_generic_message_become_blocked_not_retry():
    module = _load_module()
    p41 = "/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/大唐荣耀 (2017) S01E41-{tmdbid=70030}.mp4"
    p08 = "/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/大唐荣耀 (2017) S01E08-{tmdbid=70030}-2.mp4"
    members = [_Member(p41), _Member(p08)]
    item = _Item(members)
    plugin = _Plugin([p41, p08])

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            return object()

    class Exec:
        @staticmethod
        def _execute_isolated_transfer(plugin, item):
            return False, "整理任务处理失败，请稍后重试"

        @staticmethod
        def _fallback_terminal_state(plugin, item, success, message):
            if success:
                return
            for member in plugin._v360_members(item):
                if member.path in plugin.store.inflight:
                    plugin.store.retry.add(member.path)
                    plugin.store.inflight.discard(member.path)

        @staticmethod
        def api_organize_monitor_status(plugin):
            return {"success": True, "data": {"status": {}}}

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    module._execution_class = lambda: Exec
    module._monitor_class = lambda: Exec

    def persist(plugin, row, member):
        plugin.store.inflight.discard(member.path)
        plugin.store.retry.discard(member.path)
        plugin.store.blocked.add(member.path)
        return "blocked"

    module._persist_probe_conflict = persist
    module.install_admission_conflict_probe_v3621()
    module._remember_conflict(
        storage="光鸭云盘助手",
        src_path=p41,
        error=TransferAdmissionConflictError(f"整理源文件已按不同输入准入: 光鸭云盘助手:{p41}"),
    )
    module._remember_conflict(
        storage="光鸭云盘助手",
        src_path=p08,
        error=TransferAdmissionConflictError(f"整理源文件已按不同输入准入: 光鸭云盘助手:{p08}"),
    )

    Exec._fallback_terminal_state(plugin, item, False, "整理任务处理失败，请稍后重试")

    assert plugin.store.blocked == {p41, p08}
    assert plugin.store.retry == set()
    assert plugin.store.inflight == set()
    assert plugin.status["admission_probe_blocked"] == 2


def test_mixed_batch_blocks_exact_conflict_but_preserves_real_retry_for_other_failure():
    module = _load_module()
    conflict = "/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/E08.mp4"
    ordinary = "/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/E41.mp4"
    item = _Item([_Member(conflict), _Member(ordinary)])
    plugin = _Plugin([conflict, ordinary])

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            return object()

    class Exec:
        @staticmethod
        def _execute_isolated_transfer(plugin, item):
            return False, "整理任务处理失败，请稍后重试"

        @staticmethod
        def _fallback_terminal_state(plugin, item, success, message):
            for member in plugin._v360_members(item):
                if member.path in plugin.store.inflight:
                    plugin.store.retry.add(member.path)
                    plugin.store.inflight.discard(member.path)

        @staticmethod
        def api_organize_monitor_status(plugin):
            return {"success": True, "data": {"status": {}}}

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    module._execution_class = lambda: Exec
    module._monitor_class = lambda: Exec

    def persist(plugin, row, member):
        plugin.store.inflight.discard(member.path)
        plugin.store.blocked.add(member.path)
        return "blocked"

    module._persist_probe_conflict = persist
    module.install_admission_conflict_probe_v3621()
    module._remember_conflict(
        storage="光鸭云盘助手",
        src_path=conflict,
        error=TransferAdmissionConflictError("TransferAdmissionConflictError"),
    )
    Exec._fallback_terminal_state(plugin, item, False, "整理任务处理失败，请稍后重试")

    assert plugin.store.blocked == {conflict}
    assert plugin.store.retry == {ordinary}
    assert plugin.store.inflight == set()


def test_other_storage_or_nonmatching_path_cannot_reclassify_guangya_failure():
    module = _load_module()
    target = "/光鸭媒体库/剧集/大唐荣耀 (2017)/Season 1/E08.mp4"
    item = _Item([_Member(target)])
    plugin = _Plugin([target])

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            return object()

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    module.install_moviepilot_admission_probe_v3621()
    module._remember_conflict(
        storage="115网盘",
        src_path=target,
        error=TransferAdmissionConflictError("TransferAdmissionConflictError"),
    )
    module._remember_conflict(
        storage="光鸭云盘助手",
        src_path="/光鸭媒体库/剧集/其它/E01.mp4",
        error=TransferAdmissionConflictError("TransferAdmissionConflictError"),
    )

    assert module._take_matching_conflicts(plugin, item) == []
    assert len(module._records()) == 2


def test_status_projection_reports_v3621_probe_active():
    module = _load_module()

    class Repo(_FakeRepoBase):
        def admit(self, *args, **kwargs):
            return object()

    class Exec:
        @staticmethod
        def _execute_isolated_transfer(plugin, item):
            return True, ""

        @staticmethod
        def _fallback_terminal_state(plugin, item, success, message):
            return None

        @staticmethod
        def api_organize_monitor_status(plugin):
            return {"success": True, "data": {"status": {"runtime_hardening": "v3.6.20"}}}

    _reset_repo_class(Repo)
    module._admission_repo_class = lambda: Repo
    module._execution_class = lambda: Exec
    module._monitor_class = lambda: Exec
    module.install_admission_conflict_probe_v3621()
    response = Exec.api_organize_monitor_status(_Plugin([]))
    status = response["data"]["status"]
    assert status["runtime_hardening"] == "v3.6.21"
    assert status["admission_conflict_probe"] is True
