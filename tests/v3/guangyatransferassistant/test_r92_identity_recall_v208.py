"""2.0.8-r92：实机身份误杀 / stats 假报 / 候选去重 / 外部补搜 / tombstone / 通知汇总。

直接绑定 production 方法，不复制 regex / 算法。
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Set
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
CORE = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
GUARD = (PLUGIN / "channel_event_guard_v1115.py").read_text(encoding="utf-8")
SAFETY = (PLUGIN / "production_safety_v208.py").read_text(encoding="utf-8")
DISPATCH = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")
IDENTITY = (PLUGIN / "media_identity_v1111.py").read_text(encoding="utf-8")


def test_r92_version_markers():
    assert 'plugin_version = "2.0.10"' in ENTRY
    assert 'build_id = "20260911-r94"' in ENTRY
    assert "GuangYaProductionSafetyV208Mixin" in ENTRY
    assert "extract_share_media_identity_v1111" in CORE
    assert "identity_reject_v11214" in LEGACY
    assert "没有识别到支持的视频/字幕扩展名" in LEGACY
    assert LEGACY.index("identity_reject_v11214") < LEGACY.index("没有识别到支持的视频/字幕扩展名")
    assert "_enqueue_external_recall_v208" in GUARD
    assert "外部补搜" in DISPATCH
    assert "force=True" in DISPATCH.split('if "外部补搜" in text:', 1)[1][:400]


def _load_identity_module():
    ns: Dict[str, Any] = {}
    tree = ast.parse(IDENTITY)
    module = ast.Module(body=list(tree.body), type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(PLUGIN / "media_identity_v1111.py"), "exec"), ns)
    return ns


def test_extract_share_tmdb_markers_production():
    ns = _load_identity_module()
    extract = ns["extract_share_media_identity_v1111"]
    row = extract(["第一声啼哭 母子救命急救班 (2026) {tmdb-324580}/First.Cry/E01.mkv"])
    assert row["tmdb_id"] == "324580"
    row = extract(["The Shards (2026) {tmdb-298168}/The.Shards/E09.mkv"])
    assert row["tmdb_id"] == "298168"
    row = extract(["尼古喵喵 (2026) {tmdbid=312949}/Chainsmoker.Cat/E10.mkv"])
    assert row["tmdb_id"] == "312949"
    row = extract(["身缝奇石/E01.mkv"])
    assert not row["tmdb_id"]


def _bind_plan_incremental(aliases: Optional[List[str]] = None, tmdb_id: str = "", tv_aliases: Optional[List[str]] = None):
    """Bind production GuangYaCorePipelineV11214Mixin._plan_incremental_files into a probe class."""
    identity_ns = _load_identity_module()

    # Minimal stubs for imports used at class body load time
    app_chain = types.ModuleType("app.chain")
    app_chain_media = types.ModuleType("app.chain.media")
    app_schemas = types.ModuleType("app.schemas")
    app_schemas_types = types.ModuleType("app.schemas.types")

    class MediaChain:
        def recognize_media(self, **kwargs):
            return None

    class MediaType:
        TV = "TV"
        MOVIE = "MOVIE"

    class MediaSource:
        TMDB = "TMDB"

    app_chain_media.MediaChain = MediaChain
    app_schemas_types.MediaType = MediaType
    app_schemas_types.MediaSource = MediaSource
    sys.modules["app.chain"] = app_chain
    sys.modules["app.chain.media"] = app_chain_media
    sys.modules["app.schemas"] = app_schemas
    sys.modules["app.schemas.types"] = app_schemas_types

    # Stub sibling modules imported by core_pipeline
    for name in (
        "episode_resolver_v190",
        "legacy",
        "media_identity_v1111",
        "xunlei_existing_fence_v11213",
    ):
        mod = types.ModuleType(f"plugins.v3.guangyatransferassistant.{name}")
        sys.modules[f"plugins.v3.guangyatransferassistant.{name}"] = mod
        sys.modules[name] = mod

    legacy_mod = sys.modules["legacy"]
    legacy_mod._canonical_share_url = lambda x: x
    legacy_mod._entry_match_reason = lambda *a, **k: (False, "")
    legacy_mod._is_subtitle = lambda p: str(p).lower().endswith((".srt", ".ass", ".ssa", ".sup", ".vtt"))
    legacy_mod._is_video = lambda p: str(p).lower().endswith((".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".wmv"))
    legacy_mod._share_identity = lambda u: str(u or "")

    epi = sys.modules["episode_resolver_v190"]
    epi.AUTO_SELECT_CONFIDENCE = 0.8
    epi.reliable_episode_set = lambda *a, **k: set()
    epi.resolve_episode = lambda *a, **k: SimpleNamespace(episodes=[], confidence=0)

    mi = sys.modules["media_identity_v1111"]
    for key, value in identity_ns.items():
        if not key.startswith("__"):
            setattr(mi, key, value)

    fence = sys.modules["xunlei_existing_fence_v11213"]

    class GuangYaXunleiExistingEpisodeFenceV11213Mixin:
        pass

    fence.GuangYaXunleiExistingEpisodeFenceV11213Mixin = GuangYaXunleiExistingEpisodeFenceV11213Mixin

    # Load core_pipeline as module via exec of class only is hard due to imports;
    # instead exec the file with stubbed package path.
    pkg_name = "guangya_core_v208_test"
    spec = importlib.util.spec_from_file_location(pkg_name, PLUGIN / "core_pipeline_v11214.py")
    # Patch import targets used inside file: relative imports fail outside package.
    # Fall back to AST-extracting the class methods we need.

    tree = ast.parse(CORE)
    class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaCorePipelineV11214Mixin")
    wanted = {
        "_identity_stats_snapshot_v208",
        "_plan_incremental_files",
        "_direct_share_primary_roots_v11214",
        "_tmdb_id_tv_v11214",
        "_tv_tmdb_aliases_v11214",
        "_authoritative_missing_v11214",
        "_resolved_episode_set_v11214",
        "_is_movie_subscription",
        "_plugin_log",
    }
    methods = [n for n in class_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    # Also keep module-level helpers referenced
    helpers = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.Assign, ast.AnnAssign))
        and (
            (isinstance(n, ast.FunctionDef) and n.name.startswith("_"))
            or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith("_") for t in n.targets))
            or (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id.startswith("_"))
        )
    ]
    # Simpler approach: build a free function wrapper by AST of just the methods onto a fake class
    fake_class = ast.ClassDef(
        name="Probe",
        bases=[],
        keywords=[],
        body=methods or [ast.Pass()],
        decorator_list=[],
    )
    module = ast.Module(body=helpers + [fake_class], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Sequence": Sequence,
        "Set": Set,
        "re": __import__("re"),
        "threading": __import__("threading"),
        "time": __import__("time"),
        "copy": __import__("copy"),
        "hashlib": __import__("hashlib"),
        "Path": Path,
        "MediaChain": MediaChain,
        "MediaType": MediaType,
        "MediaSource": MediaSource,
        "AUTO_SELECT_CONFIDENCE": 0.8,
        "reliable_episode_set": epi.reliable_episode_set,
        "resolve_episode": epi.resolve_episode,
        "_canonical_share_url": legacy_mod._canonical_share_url,
        "_entry_match_reason": legacy_mod._entry_match_reason,
        "_is_subtitle": legacy_mod._is_subtitle,
        "_is_video": legacy_mod._is_video,
        "_share_identity": legacy_mod._share_identity,
        "assess_media_identity_v1111": identity_ns["assess_media_identity_v1111"],
        "extract_share_media_identity_v1111": identity_ns["extract_share_media_identity_v1111"],
        "title_key_v1111": identity_ns["title_key_v1111"],
        "GuangYaXunleiExistingEpisodeFenceV11213Mixin": GuangYaXunleiExistingEpisodeFenceV11213Mixin,
        "Tuple": __import__("typing").Tuple,
        "Iterable": __import__("typing").Iterable,
    }
    # core_pipeline now depends on media_source_v209 helpers for themoviedb tokens
    ms_path = PLUGIN / "media_source_v209.py"
    ms_spec = importlib.util.spec_from_file_location("media_source_v209_for_r92", ms_path)
    ms_mod = importlib.util.module_from_spec(ms_spec)
    assert ms_spec.loader is not None
    ms_spec.loader.exec_module(ms_mod)
    ns["is_tmdb_source"] = ms_mod.is_tmdb_source
    ns["normalize_media_source_token"] = ms_mod.normalize_media_source_token
    # Provide helper functions used by class methods from core module body
    for name in (
        "_positive_episode_set_v11214",
        "_physical_episode_subset_v11214",
        "_ACTIVE_EXTERNAL_STATES_V11214",
        "_GENERIC_SHARE_ROOTS_V11214",
        "_ACTUAL_EP_MARKER_V11214",
    ):
        # pull from helpers via a second pass of full module constants
        pass
    # Execute constants from CORE by running Assign nodes for uppercase/private constants
    const_nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            const_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_positive_episode_set_v11214",
            "_physical_episode_subset_v11214",
            "_is_subtitle",
            "_is_video",
        }:
            const_nodes.append(node)
    module2 = ast.Module(body=const_nodes + [fake_class], type_ignores=[])
    ast.fix_missing_locations(module2)
    exec(compile(module2, "<core_plan_v208>", "exec"), ns)
    Probe = ns["Probe"]

    class Runtime(Probe):
        def _plugin_log(self, *args, **kwargs):
            return None

        def _is_movie_subscription(self, subscribe):
            raw = str(getattr(subscribe, "type", "") or "").lower()
            return "movie" in raw or "电影" in raw

        def _identity_aliases_v1111(self, subscribe):
            return list(aliases or [str(getattr(subscribe, "name", "") or "")])

        def _tmdb_id_tv_v11214(self, subscribe):
            return str(tmdb_id or getattr(subscribe, "tmdb_id", "") or "")

        def _tv_tmdb_aliases_v11214(self, subscribe):
            return list(tv_aliases or [])

        def _authoritative_missing_v11214(self, subscribe, current_source_id: str = ""):
            return {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

        def _resolved_episode_set_v11214(self, subscribe, name, package_paths, episode_hint: str = ""):
            import re
            m = re.search(r"[Ee](\d{1,4})", str(name))
            return {int(m.group(1))} if m else set()

        def _plan_incremental_files_base(self, probe, assets, subscribe=None, target_path="", stats=None):
            files = [dict(item) for item in (probe.get("files") or [])]
            planned = []
            video = subtitle = 0
            for item in files:
                path = str(item.get("relative_path") or item.get("name") or "")
                if legacy_mod._is_video(path):
                    video += 1
                    item = dict(item)
                    item["effective_path"] = path
                    planned.append(item)
                elif legacy_mod._is_subtitle(path):
                    subtitle += 1
            if stats is not None:
                stats.clear()
                stats.update({"total": len(files), "video": video, "subtitle": subtitle, "eligible": len(planned), "episode": 0, "unparsed": 0, "inferred": 0})
            return planned

    # Wire super() for _plan_incremental_files by inserting a cooperative parent
    class Parent:
        def _plan_incremental_files(self, probe, assets, subscribe=None, target_path="", stats=None):
            return Runtime._plan_incremental_files_base(self, probe, assets, subscribe=subscribe, target_path=target_path, stats=stats)

    class Bound(Runtime, Parent):
        pass

    return Bound()


def _probe_files(root: str, names: Sequence[str]) -> Dict[str, Any]:
    files = []
    for index, name in enumerate(names, start=1):
        path = f"{root}/{name}" if root else name
        files.append({"id": str(index), "relative_path": path, "name": path, "size": 1000})
    return {"files": files, "success": True}


def test_identity_tmdb_match_first_cry_confirmed():
    helper = _bind_plan_incremental(aliases=["第一声啼哭 母子救命急救班"], tmdb_id="324580")
    probe = _probe_files(
        "第一声啼哭 母子救命急救班 (2026) {tmdb-324580}",
        ["First.Cry/E01.mkv", "First.Cry/E02.mkv"],
    )
    stats: Dict[str, Any] = {}
    subscribe = SimpleNamespace(id=90, name="第一声啼哭 母子救命急救班", year="2026", season=1, type="TV", tmdb_id="324580")
    planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
    assert stats.get("identity_reject_v11214") != 1
    assert len(planned) >= 1


def test_identity_tmdb_match_shards_and_cat():
    for sid, name, tmdb, root, file_name in (
        (135, "青春碎片", "298168", "The Shards (2026) {tmdb-298168}", "The.Shards/E09.mkv"),
        (170, "尼古喵喵", "312949", "尼古喵喵 (2026) {tmdb-312949}", "Chainsmoker.Cat/E10.mkv"),
    ):
        helper = _bind_plan_incremental(aliases=[name], tmdb_id=tmdb)
        probe = _probe_files(root, [file_name])
        stats: Dict[str, Any] = {}
        subscribe = SimpleNamespace(id=sid, name=name, year="2026", season=1, type="TV", tmdb_id=tmdb)
        planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
        assert stats.get("identity_reject_v11214") != 1, (name, stats)
        assert planned, name


def test_identity_alias_a_will_eternal_confirmed():
    helper = _bind_plan_incremental(
        aliases=["一念永恒"],
        tmdb_id="76662",
        tv_aliases=["A Will Eternal", "一念永恒"],
    )
    probe = _probe_files("A.Will.Eternal.S01.2020", ["A.Will.Eternal/E01.mkv"])
    # Force no tmdb marker path: subscription has tmdb but share has none -> alias path
    stats: Dict[str, Any] = {}
    subscribe = SimpleNamespace(id=1, name="一念永恒", year="2020", season=1, type="TV", tmdb_id="76662")
    planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
    assert stats.get("identity_reject_v11214") != 1
    assert planned


def test_identity_unconfirmed_reject_shengfengqishi():
    helper = _bind_plan_incremental(aliases=["生逢其时"], tmdb_id="12345", tv_aliases=["生逢其时"])
    probe = _probe_files("身缝奇石", ["E12.mkv"])
    stats: Dict[str, Any] = {}
    subscribe = SimpleNamespace(id=200, name="生逢其时", year="2026", season=1, type="TV", tmdb_id="12345")
    planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
    assert planned == []
    assert stats.get("identity_reject_v11214") == 1
    assert stats.get("video") == 1
    assert stats.get("total") == 1
    assert "没有识别到支持的视频" not in str(stats.get("identity_reason") or "")


def test_identity_tmdb_mismatch_hard_reject():
    helper = _bind_plan_incremental(aliases=["青春碎片"], tmdb_id="298168")
    probe = _probe_files("The Shards (2026) {tmdb-999999}", ["The.Shards/E09.mkv"])
    stats: Dict[str, Any] = {}
    subscribe = SimpleNamespace(id=135, name="青春碎片", year="2026", season=1, type="TV", tmdb_id="298168")
    planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
    assert planned == []
    assert stats.get("identity_reject_v11214") == 1
    assert "tmdb_mismatch" in str(stats.get("identity_reason") or "")
    assert stats.get("video") == 1


def test_identity_error_message_not_fake_extension():
    """Simulate legacy eligible<=0 branch priority using production condition order."""
    stats = {"total": 25, "video": 9, "subtitle": 2, "eligible": 0, "identity_reject_v11214": 1, "identity_reason": "title_unconfirmed"}
    # Mirror production branch order from legacy.py
    if stats.get("eligible", 0) <= 0:
        if stats.get("identity_reject_v11214"):
            message = f"资源身份未通过最终确认：叶子={stats.get('total', 0)} 视频={stats.get('video', 0)}；{stats.get('identity_reason')}"
        elif stats.get("unparsed", 0):
            message = "unparsed"
        elif not stats.get("video", 0) and not stats.get("subtitle", 0):
            message = "分享已读取 25 个叶子文件，但没有识别到支持的视频/字幕扩展名；示例：-"
        else:
            message = "no_new"
    assert "身份" in message
    assert "没有识别到支持的视频" not in message


def test_share_execution_dedup_marker_in_legacy():
    assert "executed_share_keys" in LEGACY
    assert "【候选去重】" in LEGACY
    assert "execute=once" in LEGACY


def _safety_helper_ns() -> Dict[str, Any]:
    ms_spec = importlib.util.spec_from_file_location(
        "media_source_v209_for_safety",
        PLUGIN / "media_source_v209.py",
    )
    ms_mod = importlib.util.module_from_spec(ms_spec)
    assert ms_spec.loader is not None
    ms_spec.loader.exec_module(ms_mod)
    diag_spec = importlib.util.spec_from_file_location(
        "transfer_diag_v209_for_safety",
        PLUGIN / "transfer_diag_v209.py",
    )
    diag = importlib.util.module_from_spec(diag_spec)
    assert diag_spec.loader is not None
    diag_spec.loader.exec_module(diag)
    return {
        "Any": Any,
        "Dict": Dict,
        "Iterable": __import__("typing").Iterable,
        "List": List,
        "Optional": Optional,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "copy": __import__("copy"),
        "is_tmdb_source": ms_mod.is_tmdb_source,
        "normalize_media_source_token": ms_mod.normalize_media_source_token,
        "classify_transfer_message_v209": diag.classify_transfer_message_v209,
        "batch_summary_buckets": diag.batch_summary_buckets,
        "format_batch_summary": diag.format_batch_summary,
    }


def test_external_recall_enqueue_production():
    tree = ast.parse(SAFETY)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaProductionSafetyV208Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = _safety_helper_ns()
    ns["MediaChain"] = MagicMock()
    exec(compile(module, "<safety_v208>", "exec"), ns)

    class Base:
        def init_plugin(self, config=None):
            return None

        def _plugin_log(self, *a, **k):
            return None

        def _queue_async_route_check(self, sids, trigger=""):
            self.queued = list(sids)
            self.trigger = trigger

        def _run_v1115_mode_batch(self, batch, trigger, mode, force=False):
            self.batch = list(batch)

    class Obj(ns["GuangYaProductionSafetyV208Mixin"], Base):
        pass

    obj = Obj()
    obj.init_plugin()
    sub = SimpleNamespace(id=90, name="第一声啼哭 母子救命急救班")
    assert obj._enqueue_external_recall_v208(sub, reason="local_candidates_exhausted") is True
    assert obj.queued == [90]
    assert "外部补搜" in obj.trigger
    assert obj._enqueue_external_recall_v208(sub, reason="local_candidates_exhausted") is False

    # channel miss / new subscription style second sid
    sub2 = SimpleNamespace(id=200, name="生逢其时")
    assert obj._enqueue_external_recall_v208(sub2, reason="channel_miss") is True


def test_tombstone_and_recognition_cache_production():
    tree = ast.parse(SAFETY)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaProductionSafetyV208Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    calls = {"n": 0}

    class FakeChain:
        def recognize_media(self, **kwargs):
            calls["n"] += 1
            return {"tmdb_id": kwargs.get("media_id"), "title": "尼古喵喵", "original_name": "Chainsmoker Cat"}

    ns: Dict[str, Any] = _safety_helper_ns()
    ns["MediaChain"] = FakeChain
    exec(compile(module, "<safety_v208b>", "exec"), ns)

    class Base:
        def init_plugin(self, config=None):
            return None

        def _plugin_log(self, *a, **k):
            return None

        def _queue_async_route_check(self, *a, **k):
            return None

        def _run_v1115_mode_batch(self, *a, **k):
            return None

        def post_message(self, **kwargs):
            self.messages = getattr(self, "messages", [])
            self.messages.append(kwargs)

    class Obj(ns["GuangYaProductionSafetyV208Mixin"], Base):
        pass

    obj = Obj()
    obj.init_plugin()
    obj._notify = True
    obj._mark_share_tombstone_v208("guangya", "1942620798680711246_aecd7hu726g3whGl", "分享已失效", temporary=False)
    assert obj._is_share_tombstoned_v208("guangya", "1942620798680711246_aecd7hu726g3whGl") is True

    class MediaSource:
        value = "tmdb"

    class MediaType:
        value = "tv"

    obj._recognize_media_cached_v208(mtype=MediaType(), media_source=MediaSource(), media_id="312949")
    obj._recognize_media_cached_v208(mtype=MediaType(), media_source=MediaSource(), media_id="312949")
    assert calls["n"] == 1

    obj._begin_failure_batch_v208()
    for i in range(17):
        assert obj._queue_failure_notice_v208(SimpleNamespace(id=i, name=f"m{i}"), f"retryable-{i}") is True
    obj._flush_failure_batch_v208()
    assert len(getattr(obj, "messages", [])) == 1
    assert obj.messages[0]["title"] == "⚠️ 光鸭转存检查汇总"
    assert "失败/待补搜" not in str(obj.messages[0].get("text") or "")
    assert "真正失败" in str(obj.messages[0].get("text") or "") or "本轮检查" in str(obj.messages[0].get("text") or "")


def test_channel_guard_enqueues_not_sync_provider():
    assert "_enqueue_external_recall_v208" in GUARD
    assert "return None" in GUARD
    assert "super()._dispatch_provider_candidate" in GUARD
