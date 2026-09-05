from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CONFLICT_PATH = PLUGIN / "organizer_conflict_resolution_v353.py"
POLICY_PATH = PLUGIN / "organizer_policy.py"


def _load_conflict_module():
    package_name = "shuk_v370_existing_target_runtime"
    touched = [
        "app",
        "app.schemas",
        "app.schemas.types",
        "app.sdk",
        "app.sdk.logging",
    ]
    previous = {name: sys.modules.get(name) for name in touched}

    app = types.ModuleType("app")
    schemas = types.ModuleType("app.schemas")
    types_mod = types.ModuleType("app.schemas.types")
    sdk = types.ModuleType("app.sdk")
    logging_mod = types.ModuleType("app.sdk.logging")

    class MediaType:
        MOVIE = "movie"
        TV = "tv"

    class Logger:
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

        def exception(self, *args, **kwargs):
            pass

    types_mod.MediaType = MediaType
    logging_mod.logger = Logger()
    sys.modules.update({
        "app": app,
        "app.schemas": schemas,
        "app.schemas.types": types_mod,
        "app.sdk": sdk,
        "app.sdk.logging": logging_mod,
    })

    package = types.ModuleType(package_name)
    package.__path__ = [str(PLUGIN)]
    sys.modules[package_name] = package

    policy_spec = importlib.util.spec_from_file_location(
        f"{package_name}.organizer_policy",
        POLICY_PATH,
    )
    assert policy_spec and policy_spec.loader
    policy = importlib.util.module_from_spec(policy_spec)
    sys.modules[policy_spec.name] = policy
    policy_spec.loader.exec_module(policy)

    loss_guard = types.ModuleType(f"{package_name}.organizer_loss_guard_v349")
    empty_guard = types.ModuleType(f"{package_name}.organizer_empty_folder_guard_v3410")
    empty_guard._clear_stale_transient_state = lambda *args, **kwargs: 0
    empty_guard._live_primary_media_state = lambda *args, **kwargs: ("media", 1, "")

    folder_batch = types.ModuleType(f"{package_name}.organizer_folder_batch_v342")

    class FolderBatchEnvelope:
        pass

    folder_batch._FolderBatchEnvelope = FolderBatchEnvelope

    queue = types.ModuleType(f"{package_name}.organizer_queue_recovery")

    class QueueMixin:
        def _execute_isolated_transfer(self, item):
            return True, ""

    queue.GuangYaQueueRecoveryMixin = QueueMixin

    recognition = types.ModuleType(f"{package_name}.organizer_recognition")

    class RecognitionMixin:
        def _record_terminal_transfer(self, event, success):
            return None

    recognition.GuangYaOrganizerMixin = RecognitionMixin

    runtime = types.ModuleType(f"{package_name}.organizer_runtime")
    runtime.organizer_runtime_bound_to = lambda plugin: True

    siblings = {
        "organizer_loss_guard_v349": loss_guard,
        "organizer_empty_folder_guard_v3410": empty_guard,
        "organizer_folder_batch_v342": folder_batch,
        "organizer_queue_recovery": queue,
        "organizer_recognition": recognition,
        "organizer_runtime": runtime,
    }
    for name, module in siblings.items():
        sys.modules[f"{package_name}.{name}"] = module

    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.organizer_conflict_resolution_v353",
            CONFLICT_PATH,
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


class _File:
    def __init__(self, path: str, size, *, fileid: str = "", item_type: str = "file"):
        self.path = path
        self.name = Path(path).name
        self.size = size
        self.fileid = fileid
        self.type = item_type


class _Store:
    def __init__(self):
        self.retired = []

    def retire_path(self, *, path: str):
        self.retired.append(path)
        return True


class _Api:
    def __init__(self, *, source: _File, target: _File | None, target_path: str):
        self.source = source
        self.target = target
        self.target_path = target_path
        self.extra = {}
        self.deleted = []
        self.get_calls = []
        self.raise_target = None

    def get_item(self, path):
        value = str(path)
        self.get_calls.append(value)
        if self.raise_target == value:
            raise RuntimeError("target lookup failed")
        if value == self.target_path:
            return self.target
        return self.extra.get(value)

    def refresh_item(self, path):
        value = str(path)
        if value == self.source.path:
            return self.source
        return self.get_item(path)

    def delete(self, item):
        self.deleted.append(item.path)
        return True


class _Plugin:
    def __init__(self, api: _Api):
        self._guangya_api = api
        self.store = _Store()
        self.history = []

    @staticmethod
    def _organize_normalize_path(value):
        text = str(value).replace("\\", "/")
        return text.rstrip("/") or "/"

    def _state(self):
        return self.store

    def _append_monitor_history(self, row):
        self.history.append(dict(row))

    @staticmethod
    def _fingerprint(member):
        return f"{member.fileid}:{member.size}"


class _Item:
    def __init__(self, member: _File):
        self.members = [member]
        self.path = str(Path(member.path).parent).replace("\\", "/")
        self.name = Path(self.path).name
        self.size = int(member.size or 0)


def _scenario(source_size, target_size):
    module = _load_conflict_module()
    source_path = "/光鸭媒体库/剧集/Test/Season 1/Test S01E01.mkv"
    target_path = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    source = _File(source_path, source_size, fileid="source-id")
    target = _File(target_path, target_size, fileid="target-id")
    api = _Api(source=source, target=target, target_path=target_path)
    plugin = _Plugin(api)
    item = _Item(source)
    rows = {source_path: {"success": True, "source": source_path, "target": target_path}}
    return module, plugin, item, source, target_path, rows


def test_equal_size_existing_target_deletes_source_once_and_never_runs_real_transfer():
    module, plugin, item, source, target_path, rows = _scenario(1000, 1000)
    real_calls = []
    module._execute_member = lambda *args, **kwargs: real_calls.append((args, kwargs)) or (True, "")

    result = module._handle_single_existing_target(plugin, item, object(), {}, rows)

    assert result == (True, "同大小重复源已删除")
    assert plugin._guangya_api.deleted == [source.path]
    assert real_calls == []
    assert plugin.store.retired == [source.path]
    assert plugin.history[-1]["result"] == "duplicate_deleted_existing_target"
    assert plugin.history[-1]["target"] == target_path


def test_different_size_existing_target_never_deletes_and_runs_only_versioned_transfer():
    module, plugin, item, source, _target_path, rows = _scenario(1000, 2000)
    version_target = "/gy_media/电视剧/Test/Season 1/Test - S01E01 - 版本2.mkv"
    module._next_version_numbers = lambda *args, **kwargs: [2]
    module._single_preview_target = lambda *args, **kwargs: (version_target, "")
    calls = []

    def execute_member(plugin_arg, chain, kwargs, member, version):
        calls.append((member.path, version))
        return True, "versioned"

    module._execute_member = execute_member
    result = module._handle_single_existing_target(plugin, item, object(), {}, rows)

    assert result == (True, "versioned")
    assert plugin._guangya_api.deleted == []
    assert plugin.store.retired == []
    assert calls == [(source.path, 2)]
    assert version_target in plugin._guangya_api.get_calls


def test_unknown_size_existing_target_blocks_without_delete_or_real_transfer():
    module, plugin, item, source, _target_path, rows = _scenario(None, 2000)
    blocked = []
    calls = []
    module._mark_blocked = lambda plugin, member, reason, result: blocked.append((member.path, reason, result))
    module._execute_member = lambda *args, **kwargs: calls.append(True) or (True, "")

    result = module._handle_single_existing_target(plugin, item, object(), {}, rows)

    assert result == (True, "已有目标大小未知，源文件保持原位")
    assert blocked and blocked[0][0] == source.path
    assert blocked[0][2] == "existing_target_size_unknown"
    assert plugin._guangya_api.deleted == []
    assert calls == []


def test_target_lookup_failure_is_fail_closed_zero_delete_zero_transfer():
    module, plugin, item, source, target_path, rows = _scenario(1000, 1000)
    plugin._guangya_api.raise_target = target_path
    blocked = []
    calls = []
    module._mark_blocked = lambda plugin, member, reason, result: blocked.append((reason, result))
    module._execute_member = lambda *args, **kwargs: calls.append(True) or (True, "")

    result = module._handle_single_existing_target(plugin, item, object(), {}, rows)

    assert result == (True, "已有目标检查失败，源文件保持原位")
    assert blocked and blocked[0][1] == "existing_target_probe_blocked"
    assert plugin._guangya_api.deleted == []
    assert calls == []
