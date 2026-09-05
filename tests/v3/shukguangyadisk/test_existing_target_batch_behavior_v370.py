from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE_TEST = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_existing_target_behavior_v370.py"
spec = importlib.util.spec_from_file_location("shuk_v370_existing_target_test_support", BASE_TEST)
assert spec and spec.loader
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class _MultiApi:
    def __init__(self, *, sources, targets):
        self.sources = {item.path: item for item in sources}
        self.targets = dict(targets)
        self.deleted = []
        self.get_calls = []

    def get_item(self, path):
        value = str(path)
        self.get_calls.append(value)
        return self.targets.get(value)

    def refresh_item(self, path):
        return self.sources.get(str(path))

    def delete(self, item):
        self.deleted.append(item.path)
        return True


class _Batch:
    def __init__(self, members):
        self.members = list(members)
        self.path = "/光鸭媒体库/剧集/Test/Season 1"
        self.name = "Season 1"
        self.size = sum(int(member.size or 0) for member in members)


def test_batch_policy_handles_only_member_whose_library_target_exists():
    module = support._load_conflict_module()
    source_a = support._File("/光鸭媒体库/剧集/Test/Season 1/Test S01E01.mkv", 1000, fileid="a")
    source_b = support._File("/光鸭媒体库/剧集/Test/Season 1/Test S01E02.mkv", 2000, fileid="b")
    target_a = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    target_b = "/gy_media/电视剧/Test/Season 1/Test - S01E02.mkv"
    api = _MultiApi(
        sources=[source_a, source_b],
        targets={target_a: support._File(target_a, 1000, fileid="ta")},
    )
    plugin = support._Plugin(api)
    batch = _Batch([source_a, source_b])
    rows = {
        source_a.path: {"success": True, "source": source_a.path, "target": target_a},
        source_b.path: {"success": True, "source": source_b.path, "target": target_b},
    }

    result = module._handle_existing_target_groups(plugin, batch, object(), {}, rows)

    assert result["handled"] == {source_a.path}
    assert api.deleted == [source_a.path]
    assert plugin.store.retired == [source_a.path]
    assert source_b.path not in result["handled"]
    assert target_b in api.get_calls


def test_same_existing_target_allocates_unique_versions_for_all_different_size_sources():
    module = support._load_conflict_module()
    source_a = support._File("/光鸭媒体库/剧集/Test/Season 1/Test-A.mkv", 2000, fileid="a")
    source_b = support._File("/光鸭媒体库/剧集/Test/Season 1/Test-B.mkv", 3000, fileid="b")
    target = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    api = _MultiApi(
        sources=[source_a, source_b],
        targets={target: support._File(target, 1000, fileid="target")},
    )
    plugin = support._Plugin(api)
    batch = _Batch([source_a, source_b])
    rows = {
        source_a.path: {"success": True, "source": source_a.path, "target": target},
        source_b.path: {"success": True, "source": source_b.path, "target": target},
    }

    allocated = []

    def next_numbers(plugin_arg, target_arg, count):
        allocated.append((target_arg, count))
        return [4, 5]

    module._next_version_numbers = next_numbers
    module._single_preview_target = lambda plugin_arg, chain, kwargs, member, version: (
        f"/gy_media/电视剧/Test/Season 1/Test - S01E01 - 版本{version}.mkv",
        "",
    )
    executed = []
    module._execute_member = lambda plugin_arg, chain, kwargs, member, version: (
        executed.append((member.path, version)) or True,
        "versioned",
    )

    result = module._handle_existing_target_groups(plugin, batch, object(), {}, rows)

    assert result["handled"] == {source_a.path, source_b.path}
    assert allocated == [(target, 2)]
    assert sorted(version for _path, version in executed) == [4, 5]
    assert len({version for _path, version in executed}) == 2
    assert api.deleted == []


def test_existing_target_group_can_delete_equal_copy_and_version_different_copy_together():
    module = support._load_conflict_module()
    equal = support._File("/光鸭媒体库/剧集/Test/Season 1/equal.mkv", 1000, fileid="eq")
    version = support._File("/光鸭媒体库/剧集/Test/Season 1/version.mkv", 2200, fileid="ver")
    target = "/gy_media/电视剧/Test/Season 1/Test - S01E01.mkv"
    api = _MultiApi(
        sources=[equal, version],
        targets={target: support._File(target, 1000, fileid="target")},
    )
    plugin = support._Plugin(api)
    batch = _Batch([equal, version])
    rows = {
        equal.path: {"success": True, "source": equal.path, "target": target},
        version.path: {"success": True, "source": version.path, "target": target},
    }

    module._next_version_numbers = lambda *args, **kwargs: [7]
    module._single_preview_target = lambda plugin_arg, chain, kwargs, member, version_no: (
        f"/gy_media/电视剧/Test/Season 1/Test - S01E01 - 版本{version_no}.mkv",
        "",
    )
    executed = []
    module._execute_member = lambda plugin_arg, chain, kwargs, member, version_no: (
        executed.append((member.path, version_no)) or True,
        "versioned",
    )

    result = module._handle_existing_target_groups(plugin, batch, object(), {}, rows)

    assert result["handled"] == {equal.path, version.path}
    assert api.deleted == [equal.path]
    assert executed == [(version.path, 7)]
