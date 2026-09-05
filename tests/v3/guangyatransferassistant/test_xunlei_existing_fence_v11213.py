from __future__ import annotations

import ast
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "xunlei_existing_fence_v11213.py"
MANUAL = PLUGIN / "manual_check_v11211.py"
ENTRY = PLUGIN / "__init__.py"


def _is_video(value):
    return str(value or "").lower().endswith((".mkv", ".mp4", ".ts", ".m2ts"))


def _is_subtitle(value):
    return str(value or "").lower().endswith((".srt", ".ass", ".ssa", ".vtt"))


class _Base:
    def __init__(self):
        self.logical_missing = set(range(1, 31))
        self.sync_result = {"success": True, "existing": [], "missing": list(range(1, 31))}
        self.reserved = set()
        self.claimed = set()
        self.base_dispatch_calls = 0
        self.base_import_calls = []
        self.logs = []

    @contextmanager
    def _without_due_scope_v1120(self):
        yield

    def _subscription_missing_episodes(self, subscribe):
        return sorted(self.logical_missing)

    def _sync_media_library_progress(self, subscribe):
        return dict(self.sync_result)

    def _pending_reservations(self, subscribe):
        return {"episodes": set(self.reserved), "paths": set(), "movie": False}

    def _active_source_claims(self, sid):
        return set(self.claimed)

    @staticmethod
    def _is_movie_subscription(subscribe):
        return bool(getattr(subscribe, "movie", False))

    def _plugin_log(self, *args):
        self.logs.append(args)

    @staticmethod
    def _xunlei_file_episodes(subscribe, row, package_paths=None):
        path = str((row or {}).get("path") or (row or {}).get("name") or "")
        matched = re.search(r"(?i)E0*(\d{1,3})(?:\s*[-~]\s*E?0*(\d{1,3}))?", path)
        if not matched:
            return set()
        start = int(matched.group(1))
        end = int(matched.group(2) or start)
        return set(range(start, end + 1)) if end >= start else {start}

    def _xunlei_import_json_batch_v1123(
        self,
        subscribe,
        template,
        source_rows,
        skip_indexes=None,
        include_indexes=None,
    ):
        included = sorted(set(int(v) for v in (include_indexes or [])))
        self.base_import_calls.append(included)
        return {
            "success": True,
            "results": [{"index": index, "result": {"success": True}} for index in included],
        }

    def _dispatch_xunlei_flash(self, subscribe):
        self.base_dispatch_calls += 1
        return {"success": True, "handled": False, "episodes": [11], "successful_files": 1}

    def init_plugin(self, config=None):
        return None


def _mixin_class():
    tree = ast.parse(PATCH.read_text(encoding="utf-8"), filename=str(PATCH))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaXunleiExistingEpisodeFenceV11213Mixin"
    )
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "Iterator": Iterator,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Tuple": Tuple,
        "threading": threading,
        "contextmanager": contextmanager,
        "_is_video": _is_video,
        "_is_subtitle": _is_subtitle,
        "GuangYaGyingAliasQueryV11212Mixin": _Base,
    }
    exec(compile(module, str(PATCH), "exec"), ns)
    return ns["GuangYaXunleiExistingEpisodeFenceV11213Mixin"]


Mixin = _mixin_class()


class _Probe(Mixin):
    pass


TV = SimpleNamespace(id=262, name="择日飞升", year=2026, season=1, type="电视剧", movie=False)
MOVIE = SimpleNamespace(id=263, name="测试电影", year=2026, season=0, type="电影", movie=True)


def _rows(start=1, end=12):
    return [{"path": f"A.Good.Day.to.Ascend.S01E{episode:02d}.mkv"} for episode in range(start, end + 1)]


def test_v11213_is_nested_without_changing_top_level_mro():
    source = PATCH.read_text(encoding="utf-8")
    manual = MANUAL.read_text(encoding="utf-8")
    reconcile = (PLUGIN / "channel_reconcile_v11215.py").read_text(encoding="utf-8")
    core_final = (PLUGIN / "core_pipeline_final_v11214.py").read_text(encoding="utf-8")
    core = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    ast.parse(source, filename=str(PATCH))
    ast.parse(manual, filename=str(MANUAL))
    ast.parse(reconcile, filename=str(PLUGIN / "channel_reconcile_v11215.py"))
    ast.parse(core_final, filename=str(PLUGIN / "core_pipeline_final_v11214.py"))
    ast.parse(core, filename=str(PLUGIN / "core_pipeline_v11214.py"))
    assert 'plugin_version = "1.12.13"' in source
    assert 'build_id = "20260905-r59"' in source
    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in source
    assert "class GuangYaXunleiExistingEpisodeFenceV11213Mixin(GuangYaGyingAliasQueryV11212Mixin):" in source
    assert "class GuangYaManualCheckV11211Mixin(GuangYaChannelReconcileV11215Mixin):" in manual
    assert "class GuangYaChannelReconcileV11215Mixin(GuangYaCorePipelineFinalV11214Mixin):" in reconcile
    assert "class GuangYaCorePipelineFinalV11214Mixin(GuangYaCorePipelineV11214Mixin):" in core_final
    assert "class GuangYaCorePipelineV11214Mixin(GuangYaXunleiExistingEpisodeFenceV11213Mixin):" in core
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaXunleiExistingEpisodeFenceV11213Mixin" not in head
    assert "GuangYaCorePipelineV11214Mixin" not in head
    assert "GuangYaCorePipelineFinalV11214Mixin" not in head
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaResourceGateV1127Mixin")


def test_user_repro_library_e01_e09_plus_channel_e10_becomes_only_e11_e30():
    probe = _Probe()
    probe.sync_result = {
        "success": True,
        "existing": list(range(1, 10)),
        "missing": list(range(10, 31)),
    }
    probe.logical_missing = set(range(1, 10)) | set(range(11, 31))
    allowed, sync = probe._xunlei_authoritative_missing_v11213(TV)
    assert sync["existing"] == list(range(1, 10))
    assert allowed == set(range(11, 31))
    assert not set(range(1, 11)).intersection(allowed)


def test_authoritative_target_only_shrinks_for_reservations_and_active_claims():
    probe = _Probe()
    probe.sync_result = {"success": True, "existing": list(range(1, 10)), "missing": list(range(10, 31))}
    probe.logical_missing = set(range(10, 31))
    probe.reserved = {11, 12}
    probe.claimed = {13}
    allowed, _ = probe._xunlei_authoritative_missing_v11213(TV)
    assert allowed == set(range(10, 31)) - {11, 12, 13}


def test_tv_library_sync_failure_fails_closed_before_any_xunlei_dispatch():
    probe = _Probe()
    probe.sync_result = {"success": False, "existing": [], "missing": list(range(1, 31)), "message": "library unavailable"}
    result = probe._dispatch_xunlei_flash(TV)
    assert result["success"] is False
    assert result["handled"] is False
    assert result["fence_fail_closed_v11213"] is True
    assert probe.base_dispatch_calls == 0
    assert "跳过迅雷秒传" in result["message"]


def test_movie_path_is_unchanged_and_does_not_require_episode_library_sync():
    probe = _Probe()
    probe.sync_result = {"success": False, "message": "should not matter"}
    result = probe._dispatch_xunlei_flash(MOVIE)
    assert result["success"] is True
    assert probe.base_dispatch_calls == 1


def test_scope_forces_every_downstream_missing_read_to_hard_whitelist():
    probe = _Probe()
    probe.logical_missing = set(range(1, 31))
    with probe._xunlei_fence_scope_v11213(TV, set(range(11, 31)), set(range(1, 10))):
        assert probe._subscription_missing_episodes(TV) == list(range(11, 31))
    assert probe._subscription_missing_episodes(TV) == list(range(1, 31))


def test_json_final_fence_drops_existing_e01_e10_and_keeps_only_e11_e12():
    probe = _Probe()
    rows = _rows(1, 12)
    keep, blocked = probe._filter_xunlei_import_indexes_v11213(
        TV,
        rows,
        include_indexes=range(12),
        allowed=set(range(11, 31)),
    )
    assert keep == {10, 11}
    assert blocked == set(range(10))


def test_cross_boundary_multi_episode_file_is_rejected_as_indivisible():
    probe = _Probe()
    rows = [
        {"path": "A.Good.Day.to.Ascend.S01E09-E11.mkv"},
        {"path": "A.Good.Day.to.Ascend.S01E12.mkv"},
    ]
    keep, blocked = probe._filter_xunlei_import_indexes_v11213(
        TV,
        rows,
        include_indexes={0, 1},
        allowed=set(range(11, 31)),
    )
    assert 0 in blocked
    assert keep == {1}


def test_batch_importer_receives_only_current_real_missing_indexes():
    probe = _Probe()
    rows = _rows(1, 12)
    template = {"files": [dict(row) for row in rows]}
    probe.logical_missing = set(range(1, 10)) | set(range(11, 31))
    with probe._xunlei_fence_scope_v11213(TV, set(range(11, 31)), set(range(1, 10))):
        result = probe._xunlei_import_json_batch_v1123(
            TV,
            template,
            rows,
            include_indexes=range(12),
        )
    assert result["success"] is True
    assert probe.base_import_calls == [[10, 11]]
    assert result["fence_blocked_v11213"] == 10
    assert result["fence_allowed_episodes_v11213"] == list(range(11, 31))


def test_batch_import_is_fully_blocked_when_share_only_contains_existing_episodes():
    probe = _Probe()
    rows = _rows(1, 6)
    template = {"files": [dict(row) for row in rows]}
    probe.logical_missing = set(range(11, 31))
    with probe._xunlei_fence_scope_v11213(TV, set(range(11, 31)), set(range(1, 11))):
        result = probe._xunlei_import_json_batch_v1123(
            TV,
            template,
            rows,
            include_indexes=range(6),
        )
    assert result["success"] is False
    assert probe.base_import_calls == []
    assert result["fence_blocked_v11213"] == 6
    assert "阻止重复秒传" in result["message"]
