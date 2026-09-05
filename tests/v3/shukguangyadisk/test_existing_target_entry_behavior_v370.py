from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE_TEST = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_existing_target_behavior_v370.py"
BATCH_TEST = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_existing_target_batch_behavior_v370.py"

base_spec = importlib.util.spec_from_file_location("shuk_v370_existing_target_entry_support", BASE_TEST)
assert base_spec and base_spec.loader
base = importlib.util.module_from_spec(base_spec)
base_spec.loader.exec_module(base)

batch_spec = importlib.util.spec_from_file_location("shuk_v370_existing_target_batch_support", BATCH_TEST)
assert batch_spec and batch_spec.loader
batch_support = importlib.util.module_from_spec(batch_spec)
batch_spec.loader.exec_module(batch_support)


def _wire_preview(module, rows, details):
    class _Chain:
        def do_transfer(self, **kwargs):
            return object()

    chain = _Chain()
    module._live_primary_media_state = lambda *args, **kwargs: ("media", len(rows), "")
    module._loss_guard._build_moviepilot_kwargs = lambda *args, **kwargs: (chain, None, {}, None)
    module._loss_guard._audit_preview = lambda *args, **kwargs: (
        not bool(details.get("duplicate_targets") or details.get("missing") or details.get("failed") or details.get("empty_target")),
        "preview guard",
        details,
    )
    module._preview_member_rows = lambda *args, **kwargs: (dict(rows), "")
    return chain


def test_execute_entry_applies_existing_target_policy_even_when_preview_has_duplicate_targets():
    module = base._load_conflict_module()
    equal = base._File("/光鸭媒体库/剧集/Test/Season 1/equal.mkv", 1000, fileid="eq")
    version = base._File("/光鸭媒体库/剧集/Test/Season 1/version.mkv", 2200, fileid="ver")
    target = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    api = batch_support._MultiApi(
        sources=[equal, version],
        targets={target: base._File(target, 1000, fileid="target")},
    )
    plugin = base._Plugin(api)
    item = batch_support._Batch([equal, version])
    item.batch_id = "batch-entry"
    rows = {
        equal.path: {"success": True, "source": equal.path, "target": target},
        version.path: {"success": True, "source": version.path, "target": target},
    }
    details = {
        "expected": 2,
        "missing": [],
        "failed": [],
        "empty_target": [],
        "duplicate_targets": {target: [equal.path, version.path]},
    }
    _wire_preview(module, rows, details)
    module._next_version_numbers = lambda *args, **kwargs: [6]
    module._single_preview_target = lambda plugin_arg, chain, kwargs, member, version_no: (
        f"/gy_media/电视剧/Test/Season 1/Test - S01E01 - 版本{version_no}.mkv",
        "",
    )
    executed = []
    module._execute_member = lambda plugin_arg, chain, kwargs, member, version_no: (
        executed.append((member.path, version_no)) or True,
        "versioned",
    )

    result = module._execute_conflict_aware(plugin, item)

    assert result[0] is True
    assert api.deleted == [equal.path]
    assert executed == [(version.path, 6)]
    assert plugin.store.retired == [equal.path]


def test_execute_entry_never_runs_destructive_policy_when_preview_member_facts_are_incomplete():
    module = base._load_conflict_module()
    source = base._File("/光鸭媒体库/剧集/Test/Season 1/Test S01E01.mkv", 1000, fileid="src")
    target = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    api = batch_support._MultiApi(
        sources=[source],
        targets={target: base._File(target, 1000, fileid="target")},
    )
    plugin = base._Plugin(api)
    item = batch_support._Batch([source])
    item.batch_id = "batch-incomplete"
    rows = {source.path: {"success": True, "source": source.path, "target": target}}
    details = {
        "expected": 1,
        "missing": [source.path],
        "failed": [],
        "empty_target": [],
        "duplicate_targets": {},
    }
    _wire_preview(module, rows, details)
    called = []
    module._handle_existing_target_groups = lambda *args, **kwargs: called.append(True) or {"handled": set()}
    module._block_guard_failure = lambda *args, **kwargs: (False, "blocked")

    result = module._execute_conflict_aware(plugin, item)

    assert result == (False, "blocked")
    assert called == []
    assert api.deleted == []


def test_partial_existing_target_cleanup_does_not_reblock_remaining_member_due_to_stale_safe_flag():
    module = base._load_conflict_module()
    duplicate = base._File("/光鸭媒体库/剧集/Test/Season 1/E01.mkv", 1000, fileid="e1")
    fresh = base._File("/光鸭媒体库/剧集/Test/Season 1/E02.mkv", 2000, fileid="e2")
    duplicate_target = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    fresh_target = "/gy_media/电视剧/Test/Season 1/Test - S01E02.mkv"
    api = batch_support._MultiApi(
        sources=[duplicate, fresh],
        targets={duplicate_target: base._File(duplicate_target, 1000, fileid="target")},
    )
    plugin = base._Plugin(api)
    item = batch_support._Batch([duplicate, fresh])
    item.batch_id = "batch-partial"
    rows = {
        duplicate.path: {"success": True, "source": duplicate.path, "target": duplicate_target},
        fresh.path: {"success": True, "source": fresh.path, "target": fresh_target},
    }
    # 模拟原始目录预览里存在 duplicate_targets 导致 safe=False；该冲突成员会被 existing policy 收口。
    details = {
        "expected": 2,
        "missing": [],
        "failed": [],
        "empty_target": [],
        "duplicate_targets": {duplicate_target: [duplicate.path, "/synthetic/old-copy.mkv"]},
    }
    _wire_preview(module, rows, details)
    executed = []
    module._execute_member = lambda plugin_arg, chain, kwargs, member, version_no: (
        executed.append((member.path, version_no)) or True,
        "ok",
    )

    result = module._execute_conflict_aware(plugin, item)

    assert result[0] is True
    assert api.deleted == [duplicate.path]
    assert executed == [(fresh.path, None)]
