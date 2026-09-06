from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = PLUGIN / "empty_dir_guard_v11218.py"
MOVIE = PLUGIN / "movie_identity_v1129.py"


def _normalize(value, default="/"):
    raw = str(value if value not in (None, "") else default).replace("\\", "/")
    parts = [p for p in raw.split("/") if p and p not in {".", ".."}]
    return "/" + "/".join(parts) if parts else "/"


def _safe_relative(value):
    return "/".join(p for p in str(value or "").replace("\\", "/").split("/") if p and p not in {".", ".."})


class Item:
    def __init__(self, path, fileid=None, item_type="dir"):
        self.path = str(path)
        self.fileid = str(fileid or self.path)
        self.type = item_type
        self.name = Path(self.path).name or "/"


class FakeApi:
    def __init__(self, existing=None):
        self.items = {"/": Item("/", "", "dir")}
        for path in existing or []:
            self._ensure(path)
        self.get_folder_calls = []
        self.get_item_calls = []
        self.deleted = []
        self.list_raises = False
        self.add_child_on_create = False

    @staticmethod
    def norm(path):
        return _normalize(str(path), "/")

    def _ensure(self, path):
        normalized = self.norm(path)
        current = ""
        for part in normalized.strip("/").split("/") if normalized != "/" else []:
            current += "/" + part
            self.items.setdefault(current, Item(current))
        return self.items.get(normalized)

    def get_item(self, path):
        normalized = self.norm(path)
        self.get_item_calls.append(normalized)
        return self.items.get(normalized)

    def get_folder(self, path):
        normalized = self.norm(path)
        self.get_folder_calls.append(normalized)
        item = self._ensure(normalized)
        if self.add_child_on_create and normalized != "/":
            child = normalized.rstrip("/") + "/late.mkv"
            self.items[child] = Item(child, item_type="file")
        return item

    def list(self, folder):
        if self.list_raises:
            raise RuntimeError("list unavailable")
        parent = self.norm(folder.path)
        prefix = parent.rstrip("/") + "/"
        rows = []
        for path, item in self.items.items():
            if path == parent or not path.startswith(prefix):
                continue
            tail = path[len(prefix):]
            if "/" not in tail:
                rows.append(item)
        return rows

    def delete(self, folder):
        path = self.norm(folder.path)
        if self.list(folder):
            return False
        self.deleted.append(path)
        self.items.pop(path, None)
        return True

    def _invalidate_path_cache(self, _path):
        return None


class _Base:
    def __init__(self):
        self._save_path = "/library"
        self.api = FakeApi(existing=["/library"])
        self.logs = []
        self.source = {"id": "src1", "type": "magnet", "state": "new", "task_id": "", "enabled": True}
        self.offline_resolve_error = None
        self.offline_resolve_calls = 0
        self.offline_result = {"success": False, "message": "create failed"}
        self.xunlei_result = {"success": False, "reason": "token miss"}
        self.restore_result = {"success": False, "message": "restore failed", "completed_items": [], "task_ids": []}
        self.verified_group = {"success": True, "verified_items": []}
        self.subscription = SimpleNamespace(id=1, name="Demo")

    def _plugin_log(self, *args):
        self.logs.append(args)

    def _get_guangya_runtime(self):
        return object(), self.api

    def _target_path(self, _subscribe):
        return "/library/Demo (2026)"

    def _source_store(self):
        return {"items": {"src1": dict(self.source)}}

    def _resolve_offline_source(self, source, subscribe):
        self.offline_resolve_calls += 1
        if self.offline_resolve_error:
            raise RuntimeError(self.offline_resolve_error)
        return {"resolved_name": "Demo", "resolved_url": source.get("uri", "magnet:?xt=x"), "selected_indexes": [0], "resolve_data": {}}

    def _offline_target_parent(self, subscribe):
        target = self._target_path(subscribe)
        folder = self.api.get_folder(Path(target))
        return target, folder.fileid

    def _submit_offline_source(self, _source_id):
        try:
            self._offline_target_parent(self.subscription)
            self._resolve_offline_source(self.source, self.subscription)
            return dict(self.offline_result)
        except Exception as err:
            return {"success": False, "message": str(err)}

    def _xunlei_target_parent(self, subscribe, relative_path):
        base = self._target_path(subscribe)
        parent = _safe_relative(relative_path).rsplit("/", 1)[0] if "/" in _safe_relative(relative_path) else ""
        target = base.rstrip("/") + ("/" + parent if parent else "")
        folder = self.api.get_folder(Path(target))
        return target, folder.fileid

    def _xunlei_import_json_file_v1117(self, subscribe, obj, source_row):
        path = str(((obj.get("files") or [{}])[0]).get("path") or source_row.get("path") or "S01E01.mkv")
        self._xunlei_target_parent(subscribe, path)
        return dict(self.xunlei_result)

    def _rapid_transfer_xunlei_file(self, subscribe, row):
        self._xunlei_target_parent(subscribe, row.get("path") or "S01E01.mkv")
        return dict(self.xunlei_result)

    def _restore_items(self, probe, save_path, items, job_key=""):
        for item in items:
            parent = _safe_relative(item.get("target_parent") or "")
            target = _normalize(save_path, "/").rstrip("/") + ("/" + parent if parent else "")
            self.api.get_folder(Path(target or "/"))
        return dict(self.restore_result)

    def _verify_restored_group(self, api, parent_id, normalized, group, max_try=1, interval=0):
        result = dict(self.verified_group)
        if result.get("success") and not result.get("verified_items"):
            result["verified_items"] = list(group)
        return result


def _namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level:
            continue
        body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "GuangYaSearchRecallV11217Mixin": _Base,
        "_normalize_config_path": _normalize,
        "_safe_relative_path": _safe_relative,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


NS = _namespace()
Guard = NS["GuangYaEmptyDirGuardV11218Mixin"]


class Probe(Guard):
    pass


def test_runtime_chain_contains_v11218_without_removing_v11216_v11217():
    text = MOVIE.read_text(encoding="utf-8")
    assert "from .empty_dir_guard_v11218 import GuangYaEmptyDirGuardV11218Mixin" in text
    assert "GuangYaMovieBilingualIdentityV11216Mixin," in text
    assert "GuangYaEmptyDirGuardV11218Mixin," in text
    assert 'plugin_version = "1.12.18"' in SOURCE.read_text(encoding="utf-8")


def test_offline_resolve_failure_happens_before_any_directory_creation():
    probe = Probe()
    probe.offline_resolve_error = "no selectable media"
    result = probe._submit_offline_source("src1")
    assert not result["success"]
    assert probe.offline_resolve_calls == 1
    assert probe.api.get_folder_calls == []
    assert "/library/Demo (2026)" not in probe.api.items


def test_offline_create_failure_removes_only_new_empty_media_directory():
    probe = Probe()
    result = probe._submit_offline_source("src1")
    assert not result["success"]
    assert probe.offline_resolve_calls == 1  # pre-resolve is reused; no second network resolve
    assert probe.api.get_folder_calls == ["/library/Demo (2026)"]
    assert probe.api.deleted == ["/library/Demo (2026)"]
    assert "/library" in probe.api.items  # configured save root is protected


def test_preexisting_directory_is_never_deleted_on_failure():
    probe = Probe()
    probe.api = FakeApi(existing=["/library", "/library/Demo (2026)"])
    result = probe._submit_offline_source("src1")
    assert not result["success"]
    assert probe.api.deleted == []
    assert "/library/Demo (2026)" in probe.api.items


def test_new_directory_that_receives_a_file_is_never_deleted():
    probe = Probe()
    probe.api.add_child_on_create = True
    result = probe._submit_offline_source("src1")
    assert not result["success"]
    assert probe.api.deleted == []
    assert "/library/Demo (2026)/late.mkv" in probe.api.items


def test_unknown_directory_listing_fails_closed_and_keeps_directory():
    probe = Probe()
    probe.api.list_raises = True
    result = probe._submit_offline_source("src1")
    assert not result["success"]
    assert probe.api.deleted == []
    assert "/library/Demo (2026)" in probe.api.items


def test_offline_success_or_server_task_keeps_directory():
    success = Probe()
    success.offline_result = {"success": True, "data": {"task_id": "cloud-1"}}
    assert success._submit_offline_source("src1")["success"]
    assert success.api.deleted == []

    pending = Probe()
    pending.offline_result = {"success": False, "task_id": "cloud-2", "message": "server task exists"}
    assert not pending._submit_offline_source("src1")["success"]
    assert pending.api.deleted == []


def test_xunlei_failure_without_task_cleans_new_nested_directory_but_task_keeps_it():
    probe = Probe()
    obj = {"files": [{"path": "Season 1/Demo.S01E01.mkv"}]}
    result = probe._xunlei_import_json_file_v1117(probe.subscription, obj, {})
    assert not result["success"]
    assert "/library/Demo (2026)/Season 1" in probe.api.deleted
    assert "/library/Demo (2026)" in probe.api.deleted
    assert "/library" not in probe.api.deleted

    pending = Probe()
    pending.xunlei_result = {"success": False, "task_id": "upload-1", "reason": "pending"}
    pending._xunlei_import_json_file_v1117(pending.subscription, obj, {})
    assert pending.api.deleted == []


def test_direct_share_failure_without_task_cleans_empty_dirs_but_pending_does_not():
    probe = Probe()
    items = [{"target_parent": "Season 1", "effective_path": "Season 1/Demo.S01E01.mkv"}]
    result = probe._restore_items({}, "/library/Demo (2026)", items)
    assert not result["success"]
    assert "/library/Demo (2026)/Season 1" in probe.api.deleted
    assert "/library/Demo (2026)" in probe.api.deleted

    pending = Probe()
    pending.restore_result = {
        "success": False,
        "pending_verification": True,
        "completed_items": [],
        "task_ids": ["restore-1"],
    }
    pending._restore_items({}, "/library/Demo (2026)", items)
    assert pending.api.deleted == []


def test_pending_verification_is_read_only_and_never_calls_get_folder():
    probe = Probe()
    items = [{"target_parent": "Season 1", "effective_path": "Season 1/Demo.S01E01.mkv"}]
    result = probe._verify_restored_items("/library/Demo (2026)", items, max_try=1)
    assert not result["success"]
    assert "目标目录尚不存在" in result["message"]
    assert probe.api.get_folder_calls == []
    assert "/library/Demo (2026)/Season 1" not in probe.api.items


def test_cleanup_never_deletes_root_or_configured_save_root():
    probe = Probe()
    txn, owner = probe._dir_guard_begin_v11218("manual-test")
    txn["created_candidates"].update({"/", "/library"})
    probe._dir_guard_end_v11218(txn, owner, cleanup=True)
    assert probe.api.deleted == []
    assert "/library" in probe.api.items
