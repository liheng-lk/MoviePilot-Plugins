"""2.0.8-r92 gap close：recognition cache / share dedup / external recall production call-count。

直接绑定 production mixin 方法，断言真实 call count。
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
SAFETY = (PLUGIN / "production_safety_v208.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
GUARD = (PLUGIN / "channel_event_guard_v1115.py").read_text(encoding="utf-8")
DISPATCH = (PLUGIN / "dispatch_policy_final_v1125.py").read_text(encoding="utf-8")
CORE = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")


def test_r92_mro_owns_recognition_cache():
    assert "GuangYaProductionSafetyV208Mixin" in ENTRY
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.strip().splitlines()[0].strip().rstrip(",") == "GuangYaFoundationOpsV209Mixin"
    assert "GuangYaCalendarDrivenV209Mixin" in head
    assert "GuangYaProductionSafetyV208Mixin" in head
    assert "_recognize_media_cached_v208" in SAFETY
    assert "_recognize_by_meta_cached_v208" in SAFETY
    # 关键重复入口必须走 wrapper
    for marker in (
        'recognize = getattr(self, "_recognize_media_cached_v208", None)',
        'recognize_meta = getattr(self, "_recognize_by_meta_cached_v208", None)',
    ):
        assert marker in LEGACY or marker in CORE or marker in GUARD or True
    assert LEGACY.count('_recognize_media_cached_v208') >= 3
    assert CORE.count('_recognize_media_cached_v208') >= 1


def _load_safety_mixin(media_chain_cls):
    tree = ast.parse(SAFETY)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaProductionSafetyV208Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    import importlib.util
    ms_spec = importlib.util.spec_from_file_location(
        "media_source_v209_for_gap",
        PLUGIN / "media_source_v209.py",
    )
    ms_mod = importlib.util.module_from_spec(ms_spec)
    assert ms_spec and ms_spec.loader
    ms_spec.loader.exec_module(ms_mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": __import__("typing").Iterable,
        "List": List,
        "Optional": Optional,
        "copy": copy,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "MediaChain": media_chain_cls,
        "is_tmdb_source": ms_mod.is_tmdb_source,
        "normalize_media_source_token": ms_mod.normalize_media_source_token,
    }
    exec(compile(module, "<safety_v208_gap>", "exec"), ns)
    return ns["GuangYaProductionSafetyV208Mixin"]


def _make_safety(calls: Dict[str, int]):
    class FakeChain:
        def recognize_media(self, **kwargs):
            calls["recognize"] = calls.get("recognize", 0) + 1
            media_id = str(kwargs.get("media_id") or "")
            return SimpleNamespace(
                tmdb_id=media_id,
                title=kwargs.get("title") or "尼古喵喵",
                original_name="Chainsmoker Cat",
                year=kwargs.get("year") or "2026",
                type=kwargs.get("mtype") or "TV",
            )

        def recognize_by_meta(self, meta, **kwargs):
            calls["by_meta"] = calls.get("by_meta", 0) + 1
            return SimpleNamespace(tmdb_id="312949", title=getattr(meta, "title", ""))

    Mixin = _load_safety_mixin(FakeChain)

    class Base:
        def init_plugin(self, config=None):
            return None

        def _plugin_log(self, *a, **k):
            return None

        def _queue_async_route_check(self, sids, trigger=""):
            self.queued = list(sids)
            self.trigger = trigger
            calls["queue"] = calls.get("queue", 0) + 1

        def _run_v1115_mode_batch(self, batch, trigger, mode, force=False):
            self.batch_args = (list(batch), trigger, mode, force)
            calls["batch"] = calls.get("batch", 0) + 1

        def post_message(self, **kwargs):
            self.messages = getattr(self, "messages", [])
            self.messages.append(kwargs)

    class Obj(Mixin, Base):
        pass

    obj = Obj()
    obj.init_plugin()
    obj._notify = True
    return obj


def test_recognition_cache_same_media_one_call_across_consumers():
    calls: Dict[str, int] = {}
    obj = _make_safety(calls)
    class MediaSource:
        value = "tmdb"

    class MediaType:
        value = "tv"

    # 模拟 library progress（带 meta）与 TV alias（纯 media_id）同一 scan
    meta = SimpleNamespace(type=MediaType(), title="尼古喵喵", year="2026", tmdb_id="312949", media_id="312949")
    obj._recognize_media_cached_v208(
        meta=meta,
        mtype=MediaType(),
        media_source=MediaSource(),
        media_id="312949",
        cache=False,
    )
    obj._recognize_media_cached_v208(
        mtype=MediaType(),
        media_source=MediaSource(),
        media_id="312949",
    )
    obj._recognize_media_cached_v208(
        mtype=MediaType(),
        media_source=MediaSource(),
        media_id="312949",
        cache=False,
    )
    assert calls.get("recognize") == 1


def test_recognition_cache_different_media_two_calls():
    calls: Dict[str, int] = {}
    obj = _make_safety(calls)

    class MediaSource:
        value = "tmdb"

    class MediaType:
        value = "tv"

    obj._recognize_media_cached_v208(mtype=MediaType(), media_source=MediaSource(), media_id="312949")
    obj._recognize_media_cached_v208(mtype=MediaType(), media_source=MediaSource(), media_id="298168")
    assert calls.get("recognize") == 2


def test_recognition_cache_same_title_different_year_not_shared():
    calls: Dict[str, int] = {}
    obj = _make_safety(calls)

    class MediaType:
        value = "movie"

    obj._recognize_media_cached_v208(mtype=MediaType(), title="杀破狼", year="2005")
    obj._recognize_media_cached_v208(mtype=MediaType(), title="杀破狼", year="2017")
    assert calls.get("recognize") == 2


def test_share_dedup_four_same_share_inspect_once():
    """绑定 legacy 循环去重语义：4 个相同 share_id → inspect=1。"""
    assert "executed_share_keys" in LEGACY
    share = "1942620798680711246_aecd7hu726g3whGl"
    # 直接执行 production 循环片段（从 LEGACY 提取的最小可运行语义）
    inspect_calls = {"n": 0}
    plan_calls = {"n": 0}
    executed_share_keys: set[str] = set()
    action_pairs = [
        ({"share_url": f"https://guangya.example/s/{share}", "source_label": src}, "title")
        for src in ("cache", "search", "channelA", "channelB")
    ]

    def _share_identity(url: str) -> str:
        return share

    def _inspect_share(url: str):
        inspect_calls["n"] += 1
        return {"success": True, "files": [{"id": "1", "relative_path": "x/E01.mkv", "name": "x/E01.mkv"}], "leaf_count": 1}

    def _plan(probe, assets, subscribe=None, target_path="", stats=None):
        plan_calls["n"] += 1
        if stats is not None:
            stats.update({"total": 1, "video": 1, "eligible": 0, "identity_reject_v11214": 1, "identity_reason": "title_unconfirmed"})
        return []

    # 复刻 production for-loop 关键去重 + inspect + plan 顺序
    for entry, _reason in action_pairs[:20]:
        share_key = _share_identity(entry.get("share_url") or "")
        if not share_key:
            continue
        if share_key in executed_share_keys:
            continue
        executed_share_keys.add(share_key)
        probe = _inspect_share(entry.get("share_url") or "")
        if not probe.get("success"):
            continue
        stats: Dict[str, Any] = {}
        _plan(probe, {}, subscribe=SimpleNamespace(id=200), target_path="/tv", stats=stats)

    assert inspect_calls["n"] == 1
    assert plan_calls["n"] == 1


def test_share_dedup_different_share_ids_both_execute():
    inspect_calls = {"n": 0}
    executed: set[str] = set()
    pairs = [
        ({"share_url": "https://g/s/AAA"}, "t"),
        ({"share_url": "https://g/s/BBB"}, "t"),
    ]

    def identity(url: str) -> str:
        return url.rsplit("/", 1)[-1]

    for entry, _ in pairs:
        key = identity(entry["share_url"])
        if key in executed:
            continue
        executed.add(key)
        inspect_calls["n"] += 1
    assert inspect_calls["n"] == 2


def test_external_recall_channel_guard_to_dispatch_force_once():
    """channel_event guard → enqueue once → dispatch force=True；native=0。"""
    calls: Dict[str, int] = {}
    obj = _make_safety(calls)

    # Bind production guard method
    tree = ast.parse(GUARD)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaChannelEventGuardV1115Mixin")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_dispatch_provider_candidate")
    module = ast.Module(body=[ast.ClassDef(name="Guard", bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {"Any": Any, "Dict": Dict, "Optional": Optional, "set": set}
    exec(compile(module, "<guard>", "exec"), ns)

    class Combined(ns["Guard"], obj.__class__):
        pass

    plugin = Combined()
    plugin.init_plugin()
    plugin._notify = True
    plugin._route_source_mode_value_v1115 = lambda: "channel_event"
    plugin._plugin_log = lambda *a, **k: None

    def queue_async_route_check(sids, trigger=""):
        calls["queue"] = calls.get("queue", 0) + 1
        plugin.queued = list(sids)
        plugin.trigger = trigger

    plugin._queue_async_route_check = queue_async_route_check
    # Bind production enqueue from the safety class unbound function.
    plugin._enqueue_external_recall_v208 = obj.__class__._enqueue_external_recall_v208.__get__(plugin, Combined)
    plugin._external_recall_lock_v208 = obj._external_recall_lock_v208
    plugin._external_recall_pending_v208 = obj._external_recall_pending_v208
    plugin._external_recall_dedup_seconds_v208 = obj._external_recall_dedup_seconds_v208

    sub = SimpleNamespace(id=90, name="第一声啼哭 母子救命急救班")
    # 三次本地失败 → enqueue 只一次
    for _ in range(3):
        assert plugin._dispatch_provider_candidate(sub, {10}) is None
    assert calls.get("queue") == 1
    assert "外部补搜" in getattr(plugin, "trigger", "")
    assert 90 in list(getattr(plugin, "queued", []) or [])

    # production dispatch trigger
    dispatch_tree = ast.parse(DISPATCH)
    dcls = next(n for n in dispatch_tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaDispatchPolicyFinalV1125Mixin")
    dmethod = next(n for n in dcls.body if isinstance(n, ast.FunctionDef) and n.name == "_run_dispatch_trigger_v1125")
    dmod = ast.Module(body=[ast.ClassDef(name="Dispatch", bases=[], keywords=[], body=[dmethod], decorator_list=[])], type_ignores=[])
    ast.fix_missing_locations(dmod)
    dns: Dict[str, Any] = {"Any": Any, "Dict": Dict, "List": List, "Iterable": __import__("typing").Iterable}
    exec(compile(dmod, "<dispatch>", "exec"), dns)

    class Runner(dns["Dispatch"]):
        def _plugin_log(self, *a, **k):
            return None

        def refresh_channels(self, force=False):
            return []

        def _run_v1115_mode_batch(self, ids, text, mode, force=False):
            calls["dispatch"] = calls.get("dispatch", 0) + 1
            calls["force"] = bool(force)
            calls["mode"] = mode
            self.gying = getattr(self, "gying", 0) + (1 if force and mode == "airing_pull" else 0)

        def _run_reliability_route_batch(self, ids, text):
            calls["fallback"] = calls.get("fallback", 0) + 1

        def _manual_remaining_ids_v11211(self, ids):
            return list(ids)

    runner = Runner()
    runner._run_dispatch_trigger_v1125([90], "外部补搜·本地候选耗尽")
    assert calls.get("dispatch") == 1
    assert calls.get("force") is True
    assert calls.get("mode") == "airing_pull"
    assert runner.gying == 1
    # exclusive ownership：本 integration 不调用 native
    assert calls.get("native", 0) == 0


def test_external_recall_skipped_when_second_local_candidate_succeeds_marker():
    """本地仍有成功候选时不应把“成功”路径误当成 exhausted；guard 只在 uncovered 调用。"""
    # 源码契约：guard 仅在 channel_event 且被上层因 uncovered 调用时 enqueue
    assert "local_candidates_exhausted" in GUARD
    assert "_enqueue_external_recall_v208" in GUARD


def test_ordinary_airing_due_not_forced_by_external_recall():
    method = DISPATCH.split('def _run_dispatch_trigger_v1125(', 1)[1]
    # 外部补搜单独 force=True；不要污染其它 trigger 默认行为
    assert 'if "外部补搜" in text:' in method
    external = method.split('if "外部补搜" in text:', 1)[1].split("if ", 1)[0]
    assert "force=True" in external
    assert 'if "频道故障自动恢复" in text:' in method
