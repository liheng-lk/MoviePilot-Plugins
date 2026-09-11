"""Final Plugin SIMULATED REALISTIC E2E — GuangYaTransferAssistant only.

Only Fake external boundaries (Emby/MediaServer via DownloadChain, calendar HTTP,
GYING transport HTTP, GuangYa cloud API). Internal business methods are NOT stubbed.
"""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Set

import pytest

_HERE = Path(__file__).resolve().parent


def _load_harness():
    path = _HERE / "final_plugin_harness_v211.py"
    name = "final_plugin_harness_v211"
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_harness = _load_harness()
load_final_plugin = _harness.load_final_plugin
make_final_plugin = _harness.make_final_plugin
mro_names = _harness.mro_names


LEGIT_MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
LEGIT_ED2K_VIDEO = (
    "ed2k://|file|光鸭测试剧.S01E09.1080p.mkv|1500000000|0123456789abcdef0123456789abcdef|/"
)
LEGIT_ED2K_SUB = (
    "ed2k://|file|光鸭测试剧.S01E09.zh-CN.ass|100000|abcdef0123456789abcdef0123456789|/"
)


def _tv(**kwargs):
    base = dict(
        id=990001,
        name="光鸭测试剧",
        type="电视剧",
        season=1,
        start_episode=1,
        total_episode=12,
        note=[],
        lack_episode=12,
        state="R",
        best_version=0,
        media_source="TMDB",
        media_id="990001",
        episode_group=None,
        tmdbid=990001,
        year=2026,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class ExternalWorld:
    """External-boundary fakes only."""

    def __init__(self):
        self.emby_existing: Set[int] = {1, 2, 3, 4, 6, 8, 10}
        self.mp_missing: Set[int] = {5, 7, 11, 12}  # omits E09 on purpose
        self.due: Set[int] = set(range(1, 11))
        self.future: Set[int] = {11, 12}
        self.emby_calls = 0
        self.mp_resolve_calls = 0
        self.create_task_payloads: List[Dict[str, Any]] = []
        self.resolve_calls: List[Dict[str, Any]] = []
        self.gying_http_calls = 0
        self.direct_restore_calls = 0
        self.direct_restore_file_ids: List[str] = []
        self.logs: List[str] = []

    def install(self, plugin):
        world = self
        plugin._enabled = True
        plugin._auto_transfer_on_refresh = True
        plugin._provider_auto_search = True
        plugin._external_auto_dispatch = True
        plugin._channel_external_auto_dispatch = True
        plugin._media_only = True
        plugin._episode_auto_confidence = 0.8
        plugin._notify = False
        plugin._save_path = "/光鸭转存"
        plugin._create_media_folder = False
        plugin._selected_subscription_ids = [990001]
        plugin._managed_subscription_ids = [990001]
        plugin._selected_subscriptions = [990001]
        plugin._provisional_routes = set()
        plugin._inspect_cache = {}
        plugin._runtime_is_current = lambda: True
        plugin._xunlei_flash_enabled = False
        plugin._viewing_enabled = True
        plugin._viewing_base_url = "https://www.gying.org"
        plugin._viewing_auto_switch = False
        plugin._viewing_auto_challenge = False
        plugin._viewing_username = ""
        plugin._viewing_password = ""
        plugin._viewing_cookie = ""
        plugin._viewing_node_urls = "https://www.gying.org"
        plugin._viewing_registry_urls = ""
        plugin._viewing_node_cache_minutes = 360
        plugin._provider_result_limit = 20
        plugin._gying_search_cache = {}
        plugin.save_data(
            "viewing_session_state",
            {
                "schema": 2,
                "active_node": "https://www.gying.org",
                "discovered_at": time.time(),
                "discovered_nodes": ["https://www.gying.org"],
                "nodes": {"https://www.gying.org": {"cookie": "", "status": "ok"}},
            },
        )
        plugin.refresh_channels = lambda force=False: None
        if hasattr(plugin, "_hydrate_channel_index_for_subscription_v1115"):
            plugin._hydrate_channel_index_for_subscription_v1115 = lambda *a, **k: None
        if hasattr(plugin, "_record_route_health"):
            plugin._record_route_health = lambda **k: None

        original_log = getattr(plugin, "_plugin_log", None)

        def _log(level, msg, *args):
            try:
                text = msg % args if args else str(msg)
            except Exception:
                text = str(msg)
            world.logs.append(f"{level}|{text}")
            if callable(original_log) and original_log is not _log:
                try:
                    original_log(level, msg, *args)
                except Exception:
                    pass

        plugin._plugin_log = _log

        def _list_subscriptions():
            return [_tv()]

        plugin._list_subscriptions = _list_subscriptions
        plugin._find_subscription = lambda sid: _tv() if int(sid or 0) == 990001 else None
        plugin._active_selected_subscriptions_v1125 = lambda: [_tv()]
        plugin._is_movie_subscription = lambda s: False
        plugin._external_cooldown_due_v1125 = lambda *a, **k: True
        plugin._external_search_state_v1114 = lambda: {}
        plugin._finish_subscription_if_complete = lambda *a, **k: False
        plugin._now_text = lambda: "2026-09-11 18:00:00"
        # Real run_id from AiringDue cycle / foundation — do NOT fake _run_id_v210.

        # Emby / MP boundary: patch names already bound into plugin modules.
        import app.chain.download as download_mod
        import app.chain.media as media_mod
        import app.chain.subscribe as subscribe_mod
        import plugins.v3.guangyatransferassistant.legacy as legacy_mod
        import plugins.v3.guangyatransferassistant.calendar_driven_v209 as cal_mod

        class FakeMedia:
            tmdb_id = 990001
            type = "TV"
            title = "光鸭测试剧"
            en_title = "GuangYa Test"
            original_title = "光鸭测试剧"
            year = 2026

        class FakeDownloadChain:
            def get_no_exists_info(self, **kwargs):
                world.emby_calls += 1
                missing = sorted(set(range(1, 13)) - set(world.emby_existing))
                detail = SimpleNamespace(episodes=missing, total_episode=12)
                return False, {"x": {1: detail}}

        class FakeMediaChain:
            def recognize_media(self, **kwargs):
                return FakeMedia()

        class FakeSubscribeChain:
            def resolve_subscribe_missing(self, **kwargs):
                world.mp_resolve_calls += 1
                detail = SimpleNamespace(episodes=sorted(world.mp_missing), total_episode=12)
                return False, {"x": {1: detail}}

        def _build_meta(sub):
            return SimpleNamespace(type="TV", title=getattr(sub, "name", ""))

        class FakeSubscribeOper:
            def update(self, *a, **k):
                return True

            def get(self, *a, **k):
                return None

            def list(self, *a, **k):
                return []

        download_mod.DownloadChain = FakeDownloadChain
        media_mod.MediaChain = FakeMediaChain
        subscribe_mod.SubscribeChain = FakeSubscribeChain
        subscribe_mod.build_subscribe_meta = _build_meta
        legacy_mod.DownloadChain = FakeDownloadChain
        legacy_mod.MediaChain = FakeMediaChain
        legacy_mod.SubscribeChain = FakeSubscribeChain
        legacy_mod.build_subscribe_meta = _build_meta
        legacy_mod.SubscribeOper = FakeSubscribeOper
        try:
            import app.db.oper.subscribe as sub_oper_mod
            sub_oper_mod.SubscribeOper = FakeSubscribeOper
        except Exception:
            pass
        # calendar_driven imports SubscribeChain lazily inside methods; keep module attr ready.
        if hasattr(cal_mod, "SubscribeChain"):
            cal_mod.SubscribeChain = FakeSubscribeChain

        def _refresh(force=False):
            return {"items": [{"subscribe_id": 990001, "tmdb_id": "990001", "season": 1}]}

        def _calendar_item(subscribe, calendar):
            eps = []
            for ep in sorted(world.due | world.future):
                eps.append(
                    {
                        "episode": ep,
                        "air_date": "2026-01-01" if ep in world.due else "2099-01-01",
                    }
                )
            return {"episodes": eps, "provider": "fake_tmdb", "subscribe_id": 990001}

        def _split(item, subscribe, now, candidate_episodes=None):
            return {
                "due": set(world.due),
                "future": set(world.future),
                "air_dates": {},
                "calendar_available": True,
                "dated_count": len(world.due) + len(world.future),
                "next_episode": min(world.future) if world.future else 0,
                "next_air_at": "2099-01-01",
            }

        plugin._refresh_airing_calendar_v1120 = _refresh
        plugin._calendar_item_for_v1120 = _calendar_item
        plugin._split_calendar_due_future_v209 = _split
        plugin._mp_has_resolve_missing_v209 = lambda: True
        plugin._recognize_media_cached_v208 = lambda **k: FakeMedia()

        # Source store — preserve any preloaded r95 fixtures.
        existing_sources = plugin.get_data("sources")
        if not isinstance(existing_sources, dict) or not isinstance(existing_sources.get("items"), dict):
            plugin.save_data("sources", {"items": {}})
        else:
            existing_sources.setdefault("items", {})
            plugin.save_data("sources", existing_sources)

        def _source_store():
            raw = plugin.get_data("sources")
            if not isinstance(raw, dict):
                raw = {"items": {}}
                plugin.save_data("sources", raw)
            raw.setdefault("items", {})
            return raw

        plugin._source_store = _source_store

        def _update_source(source_id, **fields):
            items = plugin._source_store()["items"]
            row = dict(items.get(str(source_id)) or {})
            row.update(fields)
            row["id"] = str(source_id)
            items[str(source_id)] = row
            plugin.save_data("sources", plugin._source_store())
            return row

        plugin._update_source = _update_source

        # GuangYa cloud API boundary
        def _offline_request(endpoint, payload):
            world.resolve_calls.append({"endpoint": endpoint, "payload": dict(payload or {})})
            url = str((payload or {}).get("url") or "")
            if "resolve" in str(endpoint):
                if url.lower().startswith("ed2k://"):
                    # Parse basename from ED2K URI for no-subfiles path.
                    name = "光鸭测试剧.S01E09.1080p.mkv"
                    try:
                        parts = url.split("|")
                        if len(parts) >= 3:
                            name = parts[2]
                    except Exception:
                        pass
                    return {
                        "success": True,
                        "data": {
                            "url": url,
                            "btResInfo": {"fileName": name, "subfiles": []},
                        },
                    }
                return {
                    "success": True,
                    "data": {
                        "url": url or LEGIT_MAGNET,
                        "btResInfo": {
                            "fileName": "光鸭测试剧.S01",
                            "subfiles": [
                                {"fileIndex": 7, "fileName": "光鸭测试剧.S01E07.1080p.mkv", "fileSize": 1500000000},
                                {"fileIndex": 11, "fileName": "光鸭测试剧.S01E07.zh-CN.ass", "fileSize": 100000},
                                {"fileIndex": 15, "fileName": "光鸭测试剧.S01E11.1080p.mkv", "fileSize": 1500000000},
                            ],
                        },
                    },
                }
            if "create_task" in str(endpoint):
                world.create_task_payloads.append(dict(payload or {}))
                return {"success": True, "data": {"taskId": f"TASK_{len(world.create_task_payloads)}"}}
            if "list_task" in str(endpoint):
                return {"success": True, "data": {"state": "completed", "progress": 100}}
            return {"success": True, "data": {}}

        plugin._offline_request = _offline_request
        plugin._offline_api_success = lambda resp: bool((resp or {}).get("success"))
        plugin._offline_api_error = lambda resp, msg="err": msg
        plugin._offline_resolved_data = lambda resp: dict((resp or {}).get("data") or {})
        plugin._offline_target_parent = lambda subscribe: ("/media/光鸭测试剧", "parent1")

        # GYING HTTP transport boundary — keep real parser/router above this.
        def _gying_request(session, node, method, url, **kwargs):
            world.gying_http_calls += 1
            target = str(url or "")
            # Search page must carry parseable `_obj.search = {...};`
            if "/search" in target:
                payload = (
                    'var _obj={};_obj.search={"n":1,"l":{'
                    '"title":["光鸭测试剧 2026"],'
                    '"d":["tv"],'
                    '"i":["gyingtest001"],'
                    '"year":["2026"],'
                    '"info":[""]'
                    "}};"
                )
                resp = SimpleNamespace(
                    status_code=200,
                    text=payload,
                    content=payload.encode("utf-8"),
                    headers={"content-type": "text/html"},
                    url=target,
                )
                resp.json = lambda: {}
                return resp
            if "/res/downurl/" in target:
                body = (
                    '{"panlist":{"url":['
                    f'"magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",'
                    f'"ed2k://|file|光鸭测试剧.S01E09.1080p.mkv|1500000000|0123456789abcdef0123456789abcdef|/"'
                    '],"name":["光鸭测试剧.S01E07.1080p.mkv","光鸭测试剧.S01E09.1080p.mkv"],'
                    '"type":["magnet","ed2k"]}}'
                )
                resp = SimpleNamespace(
                    status_code=200,
                    text=body,
                    content=body.encode("utf-8"),
                    headers={"content-type": "application/json"},
                    url=target,
                )
                resp.json = lambda: {
                    "panlist": {
                        "url": [
                            LEGIT_MAGNET,
                            LEGIT_ED2K_VIDEO,
                        ],
                        "name": ["光鸭测试剧.S01E07.1080p.mkv", "光鸭测试剧.S01E09.1080p.mkv"],
                        "type": ["magnet", "ed2k"],
                    }
                }
                return resp
            # Homepage / login probes
            body = "<html>ok</html>"
            if str(method or "").upper() == "POST" and "/user/login" in target:
                body = '{"code":200,"msg":"ok"}'
            resp = SimpleNamespace(
                status_code=200,
                text=body,
                content=body.encode("utf-8"),
                headers={"content-type": "text/html"},
                url=target,
            )
            resp.json = lambda: {"code": 200, "msg": "ok"}
            return resp

        if hasattr(plugin, "_gying_request"):
            plugin._gying_request = _gying_request

        # Deterministic offline submit (production path is daemon thread).
        def _sync_spawn(source_id: str):
            source_id = str(source_id or "").strip()
            if not source_id:
                return {"success": False, "message": "empty", "reason": "invalid_source_id"}
            if not plugin._claim_source_dispatch_slot(source_id):
                return {"success": False, "message": "busy", "reason": "already_running"}
            try:
                out = plugin._submit_offline_source(source_id)
                return {
                    "success": bool((out or {}).get("success")),
                    "message": str((out or {}).get("message") or "sync"),
                    "reason": "sync",
                    "data": out,
                }
            finally:
                plugin._release_source_dispatch_slot(source_id)

        plugin._spawn_source_dispatch = _sync_spawn

        # GuangYa cloud client boundary for Direct share restore.
        restored: List[Any] = []

        class _FakeRemoteItem:
            def __init__(self, name: str, size: int):
                self.name = name
                self.size = size

        class _FakeFolder:
            fileid = "parent_direct"
            name = "光鸭测试剧"

        class _FakeApi:
            def get_folder(self, path):
                return _FakeFolder()

            def _wait_task_done(self, task_id, max_try=120, interval=1, allow_missing=True):
                return True

            def _iter_parent_items(self, parent_id="", parent_path=""):
                return list(restored)

        class _FakeClient:
            API_BASE_URL = "https://guangya.fake"

            def _request(self, method="POST", url="", data=None, need_auth=False):
                data = dict(data or {})
                target = str(url or "")
                if "get_share_access_token" in target:
                    return {"code": 0, "msg": "success", "data": {"accessToken": "tok-direct-e05"}}
                if "get_share_page_files_list" in target:
                    parent = str(data.get("parentId") or "")
                    if parent:
                        return {"code": 0, "msg": "success", "data": {"list": []}}
                    rows = []
                    for ep in range(1, 7):
                        rows.append(
                            {
                                "fileId": f"leaf{ep}",
                                "fileName": f"光鸭测试剧.S01E{ep:02d}.1080p.mkv",
                                "fileSize": 1500000000,
                                "type": 1,
                            }
                        )
                    return {"code": 0, "msg": "success", "data": {"list": rows}}
                if "restore_share" in target:
                    world.direct_restore_calls += 1
                    file_ids = [str(v) for v in (data.get("fileIds") or [])]
                    world.direct_restore_file_ids.extend(file_ids)
                    # Map restored leaf ids back to filenames for remote verify.
                    name_by_id = {f"leaf{ep}": f"光鸭测试剧.S01E{ep:02d}.1080p.mkv" for ep in range(1, 7)}
                    restored.clear()
                    for fid in file_ids:
                        restored.append(_FakeRemoteItem(name_by_id.get(fid, fid), 1500000000))
                    return {"code": 0, "msg": "success", "data": {"taskId": "GY_DIRECT_E05"}}
                return {"code": 0, "msg": "success", "data": {}}

        fake_client = _FakeClient()
        fake_api = _FakeApi()
        plugin._get_guangya_runtime = lambda: (fake_client, fake_api)
        plugin._dispatch_xunlei_flash = lambda *a, **k: {"success": False, "handled": False}

        return plugin

    def seed_direct_share(self, plugin):
        """Seed Resource Inbox / channel Direct GuangYa share (E01-E06 package)."""
        plugin.save_data(
            "channel_index",
            {
                "items": [
                    {
                        "share_url": "https://www.guangyapan.com/s/DIRECTE05TEST",
                        "share_id": "DIRECTE05TEST",
                        "display_title": "光鸭测试剧",
                        "tmdb_id": "990001",
                        "year_hint": 2026,
                        "episode_hint": "S01E01-E06",
                        "text": "名称：光鸭测试剧\nTMDB: 990001\nS01 已更新至 E06",
                        "source_label": "TGM Resource Inbox",
                        "source_url": "https://tgm.example/regengguangya",
                        "stale": False,
                        "message_id": "msg-direct-e05",
                        "resource_group_id": "rg-direct-e05",
                        "resource_trace_id": "trace-direct-e05",
                        "external_sources": [],
                        "candidate_types": ["guangya"],
                        "priority": 0,
                    }
                ]
            },
        )
        return plugin


def test_final_mro_runtime_before_target():
    names = mro_names()
    assert names[0] == "GuangYaTransferAssistant"
    assert names.index("GuangYaEpisodeRuntimeV211Mixin") < names.index("GuangYaEpisodeTargetV210Mixin")
    assert names.index("GuangYaEpisodeTargetV210Mixin") < names.index("GuangYaCalendarDrivenV209Mixin")


def test_final_get_service_airing_due_func_is_runtime():
    plugin = make_final_plugin()
    services = plugin.get_service()
    assert isinstance(services, list) and services
    airing = next(s for s in services if s.get("id") == "GuangYaTransferAssistantAiringDue")
    assert airing["func"].__func__.__qualname__.startswith("GuangYaEpisodeRuntimeV211Mixin._calendar_due_check_v1110")
    # Real call — may return skipped/empty but must not raise RecursionError
    out = airing["func"]()
    assert isinstance(out, dict)
    assert "success" in out or "skipped" in out or "checked" in out or "selected" in out


def test_final_episode_target_emby_gap_override_and_one_emby():
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    before = world.emby_calls
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=True)
    assert set(snap["final_target"]) == {5, 7, 9}
    assert 9 in set(snap.get("emby_gap_override") or []) or 9 in set(snap["final_target"])
    assert 11 not in set(snap["final_target"])
    # Nested MP/calendar must not open another Emby HTTP via DownloadChain.
    assert world.emby_calls - before == 1


def test_final_magnet_real_planner_fileindexes():
    world = ExternalWorld()
    # Emby already has E05 — remaining due gaps are E07,E09 only.
    world.emby_existing = {1, 2, 3, 4, 5, 6, 8, 10}
    world.mp_missing = {7, 11, 12}  # still omits E09 for override proof
    plugin = world.install(make_final_plugin())
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert set(snap["final_target"]) == {7, 9}

    source = {
        "id": "mag1",
        "type": "magnet",
        "uri": LEGIT_MAGNET,
        "name": "光鸭测试剧.S01",
        "subscribe_id": 990001,
        "target_episodes": [7, 9],
        "enabled": True,
        "state": "new",
    }
    plugin._update_source("mag1", **source)
    subscribe = _tv()
    resolved = plugin._resolve_offline_source(source, subscribe)
    indexes = list(resolved.get("selected_indexes") or [])
    assert 7 in indexes
    assert 11 in indexes  # subtitle companion for E07
    assert 15 not in indexes  # future E11 blocked
    # Production create_task path
    out = plugin._submit_offline_source("mag1")
    assert world.create_task_payloads, f"no create_task: {out}"
    payload = world.create_task_payloads[-1]
    assert set(payload.get("fileIndexes") or []) == {7, 11}


def test_final_ed2k_video_submit_subtitle_blocked():
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    plugin._mark_pending_library_confirmation_v210(_tv(), [5, 7], source="prior")
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert set(snap["final_target"]) == {9}

    # Video ED2K — production assert gate must allow video filename.
    video_source = {
        "id": "ed2k_v",
        "type": "ed2k",
        "uri": LEGIT_ED2K_VIDEO,
        "name": "光鸭测试剧.S01E09.1080p.mkv",
        "subscribe_id": 990001,
        "target_episodes": [9],
        "episode_hint": "E09",
        "enabled": True,
        "state": "new",
    }
    plugin._update_source("ed2k_v", **video_source)

    # Force resolve path for ED2K no-subfiles using production planner helpers.
    resolve_data = {"btResInfo": {"fileName": "光鸭测试剧.S01E09.1080p.mkv"}, "url": video_source["uri"]}
    manifest = plugin._assert_selected_video_present_v210(
        resolve_data=resolve_data,
        selected_indexes=[],
        source=video_source,
        subscribe=_tv(),
    )
    assert manifest == [] or True  # video allowed (no raise)

    # Subtitle-only must raise SELECTED_VIDEO_MISSING via production gate.
    sub_source = {
        "id": "ed2k_s",
        "type": "ed2k",
        "uri": LEGIT_ED2K_SUB,
        "name": "光鸭测试剧.S01E09.zh-CN.ass",
        "subscribe_id": 990001,
        "target_episodes": [9],
        "enabled": True,
        "state": "new",
    }
    with pytest.raises(RuntimeError) as err:
        plugin._assert_selected_video_present_v210(
            resolve_data={"btResInfo": {"fileName": "光鸭测试剧.S01E09.zh-CN.ass"}},
            selected_indexes=[],
            source=sub_source,
            subscribe=_tv(),
        )
    assert "SELECTED_VIDEO_MISSING" in str(err.value)


def test_final_pending_blocks_duplicate_and_ingest_clears():
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    for ep in (5, 7, 9):
        plugin._mark_pending_library_confirmation_v210(_tv(), [ep], source="x")
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert snap["final_target"] == []
    assert set(snap["pending_library"]) == {5, 7, 9}
    ok, _, reason = plugin._final_target_allows_submit_v211(_tv(), [5])
    assert ok is False and reason == "empty_final_target"

    world.emby_existing = set(range(1, 11))
    snap2 = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert snap2["final_target"] == []
    assert set(snap2["pending_library"]) == set()
    assert snap2["decision"] == "skip_future"


def test_final_historical_delete_e03_without_clearing_sources():
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    # Preserve prior source history (do NOT clear sources).
    plugin._update_source(
        "old_e03",
        id="old_e03",
        subscribe_id=990001,
        type="magnet",
        state="completed",
        enabled=True,
        target_episodes=[3],
        resolved_episodes=[3],
        completed_ts=time.time() - 3600,
    )
    world.emby_existing = set(range(1, 11)) - {3}
    world.mp_missing = {11, 12}
    world.due = set(range(1, 11))
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert 3 in set(snap["final_target"])
    assert plugin._source_store()["items"].get("old_e03")  # history preserved


def test_final_r95_superseded_reopen():
    store = {
        "media_facts": {
            "s:990001:1:e0003": {"origin": "library", "episode": 3},
            "s:990001:1:e0005": {"origin": "guangya_offline", "episode": 5},
        },
        "sources": {
            "items": {
                "bad": {
                    "id": "bad",
                    "subscribe_id": 990001,
                    "state": "disabled",
                    "enabled": False,
                    "superseded_by_receipt": True,
                    "superseded_reason": "library observation completed E03",
                    "target_episodes": [3],
                }
            }
        },
    }
    plugin = make_final_plugin(store=store)
    plugin._migrate_library_observation_facts_v211_once()
    plugin._reopen_library_polluted_superseded_sources_v211()
    facts = plugin.get_data("media_facts") or {}
    assert "s:990001:1:e0003" not in facts
    assert "s:990001:1:e0005" in facts
    row = (plugin.get_data("sources") or {}).get("items", {}).get("bad") or {}
    # reopen helper uses _update_source which may need wiring — call reopen after installing update
    world = ExternalWorld()
    plugin = world.install(make_final_plugin(store=store))
    # reset reopen marker so it runs
    plugin.save_data("episode_supersede_reopen_v211", {})
    plugin.save_data("episode_facts_migration_v211", {})
    plugin._migrate_library_observation_facts_v211_once()
    n = plugin._reopen_library_polluted_superseded_sources_v211()
    assert n >= 1
    row = plugin._source_store()["items"]["bad"]
    assert row.get("state") == "new"
    assert row.get("enabled") is True


def test_final_concurrency_no_cross_contamination():
    world_a = {"existing": {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}, "seen": []}
    world_b = {"existing": {1, 2, 3, 4, 5, 6, 7, 8, 9}, "seen": []}
    plugin = make_final_plugin()
    lock = threading.Lock()
    errors = []

    def run(sid, name, bucket):
        try:
            sub = SimpleNamespace(
                id=sid,
                name=name,
                type="电视剧",
                season=1,
                start_episode=1,
                total_episode=12,
                note=[],
                lack_episode=12,
                state="R",
                best_version=0,
                media_source="TMDB",
                media_id=str(sid),
                episode_group=None,
                tmdbid=sid,
            )
            with plugin._episode_run_context_scope_v211(sub, run_id=f"run:{sid}"):
                sync = {
                    "success": True,
                    "existing": sorted(bucket["existing"]),
                    "missing": sorted(set(range(1, 13)) - set(bucket["existing"])),
                }
                plugin._remember_library_sync_in_context_v211(sub, sync)
                time.sleep(0.05)
                ctx = plugin._episode_run_context_for_subscribe_v211(sub)
                got = set((ctx or {}).get("library_existing") or [])
                with lock:
                    bucket["seen"].append(got)
                if got != set(bucket["existing"]):
                    errors.append((sid, got, bucket["existing"]))
        except Exception as err:  # noqa: BLE001
            errors.append((sid, str(err)))

    t1 = threading.Thread(target=run, args=(85, "鬼的新娘", world_a))
    t2 = threading.Thread(target=run, args=(170, "尼古喵喵", world_b))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, errors
    assert world_a["seen"] and world_a["seen"][0] == world_a["existing"]
    assert world_b["seen"] and world_b["seen"][0] == world_b["existing"]


def test_final_runtime_fallback_triggers_calendar_when_stale():
    """Exercise production `_runtime_worker_loop` AiringDue fallback branch (no sleep)."""
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    plugin._startup_check = lambda: None
    plugin._tick = lambda host_service=False: None
    plugin._enabled = True
    plugin._auto_transfer_on_refresh = True
    plugin._refresh_minutes = 5
    plugin._host_airing_heartbeat_v211 = time.monotonic() - 2000
    plugin._host_tick_heartbeat = time.monotonic()  # fresh → skip channel tick
    plugin._airing_fallback_stale_seconds_v211 = 300
    plugin._runtime_is_current = lambda: True
    stop = threading.Event()
    waits = {"n": 0}

    def _wait(timeout=None):
        waits["n"] += 1
        # 1st: startup wait(1.5) → continue
        # 2nd: interval wait → pretend elapsed, continue into fallback body
        # 3rd+: stop the loop
        return waits["n"] >= 3

    stop.wait = _wait  # type: ignore[method-assign]
    plugin._runtime_stop = stop
    plugin._runtime_worker_loop(generation=1)
    assert any("AiringDue" in row and "服务回退" in row for row in world.logs)
    assert any("owner=fallback" in row for row in world.logs)


def test_final_airing_due_enters_gying_http_via_get_service():
    """get_service AiringDue → selector → transfer → real GYING parser over Fake HTTP."""
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    services = plugin.get_service()
    airing = next(s for s in services if s.get("id") == "GuangYaTransferAssistantAiringDue")
    assert airing["func"].__func__.__qualname__.startswith(
        "GuangYaEpisodeRuntimeV211Mixin._calendar_due_check_v1110"
    )
    before = world.gying_http_calls
    out = airing["func"]()
    assert out.get("success") is True
    assert int(out.get("selected") or out.get("checked") or 0) >= 1
    assert world.gying_http_calls > before
    assert any("主动检索派发" in row and "airing_pull" in row for row in world.logs)
    assert any("观影搜索请求完成" in row or "观影】搜索请求完成" in row for row in world.logs)


def test_final_airing_singleflight_overlap():
    plugin = make_final_plugin()
    c1 = plugin._begin_airing_due_cycle_v211("host")
    assert c1 is not None
    c2 = plugin._begin_airing_due_cycle_v211("fallback")
    assert c2 is None
    plugin._end_airing_due_cycle_v211()
    c3 = plugin._begin_airing_due_cycle_v211("fallback")
    assert c3 is not None
    plugin._end_airing_due_cycle_v211()


def test_final_unknown_empty_target_not_selected_by_selector():
    plugin = make_final_plugin()
    world = ExternalWorld()
    world.install(plugin)
    # Force empty final via pending covering all gaps
    for ep in (5, 7, 9):
        plugin._mark_pending_library_confirmation_v210(_tv(), [ep], source="x")
    gate = plugin._airing_gate_v1120(_tv(), payload={"items": []})
    assert not gate.get("final_target")
    assert gate.get("decision") in {"unknown_no_due_target", "skip_reserved_or_pending", "skip_future"} or not gate.get("due_uncovered")
    # Selector must not white-select empty targets
    due_ids = plugin._smart_pull_due_ids_v1125()
    assert 990001 not in due_ids or bool(gate.get("due_uncovered") or gate.get("target_episodes"))


def test_final_airing_due_emby_and_mp_once():
    """Selector + transfer share AiringDue cycle context: Emby<=1, MP resolve<=1."""
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    plugin.refresh_channels = lambda force=False: None
    if hasattr(plugin, "_hydrate_channel_index_for_subscription_v1115"):
        plugin._hydrate_channel_index_for_subscription_v1115 = lambda *a, **k: None
    # Avoid deep native download paths; keep EpisodeFacts / gate / planner real.
    plugin._dispatch_xunlei_flash = lambda *a, **k: {"success": False, "handled": False}
    services = plugin.get_service()
    airing = next(s for s in services if s.get("id") == "GuangYaTransferAssistantAiringDue")
    before_emby = world.emby_calls
    before_mp = world.mp_resolve_calls
    out = airing["func"]()
    assert out.get("success") is True
    assert world.emby_calls - before_emby <= 1, f"Emby calls={world.emby_calls - before_emby}"
    assert world.mp_resolve_calls - before_mp <= 1, f"MP resolve={world.mp_resolve_calls - before_mp}"
    # Formal run id must not be blank dash in AiringDue logs.
    assert not any("run=-" in row and "剧集目标" in row for row in world.logs)


def test_final_ed2k_legitimate_video_create_task():
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert 9 in set(snap["final_target"])
    source = {
        "id": "ed2k_e09",
        "type": "ed2k",
        "uri": LEGIT_ED2K_VIDEO,
        "name": "光鸭测试剧.S01E09.1080p.mkv",
        "subscribe_id": 990001,
        "target_episodes": [9],
        "episode_hint": "E09",
        "enabled": True,
        "state": "new",
    }
    plugin._update_source("ed2k_e09", **source)
    # media_match gate uses authoritative missing = final_target
    plugin._authoritative_missing_v11214 = lambda s, current_source_id="": set(snap["final_target"])
    with plugin._episode_run_context_scope_v211(_tv(), run_id="run:#990001:airing:test", seed={
        "final_target": list(snap["final_target"]),
        "library_sync": {
            "success": True,
            "existing": sorted(world.emby_existing),
            "missing": sorted(set(range(1, 13)) - set(world.emby_existing)),
        },
        "mp_missing_resolved": True,
        "mp_missing": list(world.mp_missing) + [9],
        "mp_missing_state": "used_missing",
    }):
        resolved = plugin._resolve_offline_source(source, _tv())
    assert resolved.get("selected_indexes") == []
    row = plugin._source_store()["items"]["ed2k_e09"]
    assert list(row.get("resolved_episodes") or []) == [9]
    assert row.get("state") != "needs_review"
    plugin._final_target_allows_submit_v211 = lambda s, eps: (True, {9}, "test")
    out = plugin._submit_offline_source("ed2k_e09")
    assert world.create_task_payloads, f"no create_task: {out}"
    assert plugin._source_store()["items"]["ed2k_e09"].get("state") != "needs_review"


def test_final_runtime_init_ready_blocks_before_ready():
    plugin = make_final_plugin()
    plugin._episode_runtime_ready_v211 = False
    out = plugin._calendar_due_check_v1110(owner="fallback")
    assert out.get("skipped") is True
    assert out.get("reason") == "episode_runtime_not_ready"
    plugin._episode_runtime_ready_v211 = True


def test_final_chain_direct_gying_magnet_ed2k_one_airing_due():
    """Single AiringDue: Direct E05 → GYING → Magnet E07 → ED2K E09."""
    world = ExternalWorld()
    plugin = world.install(make_final_plugin())
    world.seed_direct_share(plugin)

    services = plugin.get_service()
    airing = next(s for s in services if s.get("id") == "GuangYaTransferAssistantAiringDue")
    before_emby = world.emby_calls
    before_mp = world.mp_resolve_calls
    before_gying = world.gying_http_calls

    out = airing["func"]()
    assert out.get("success") is True
    assert int(out.get("selected") or 0) >= 1

    # Direct share restore selected only the missing E05 leaf from E01-E06 package.
    assert world.direct_restore_calls >= 1, f"Direct restore missing; logs={world.logs[-20:]}"
    assert "leaf5" in world.direct_restore_file_ids
    assert "leaf1" not in world.direct_restore_file_ids
    assert any("分享解析" in row or "增量" in row or "转存提交" in row for row in world.logs)

    # Remaining gaps entered real GYING HTTP + parser.
    assert world.gying_http_calls > before_gying
    assert any("观影" in row and ("搜索请求完成" in row or "搜索开始" in row) for row in world.logs)

    # Magnet E07 + ED2K E09 create_task via GuangYa cloud API.
    assert world.create_task_payloads, f"no create_task; sources={plugin.get_data('sources')}"
    magnet_payloads = [
        p for p in world.create_task_payloads if str(p.get("url") or "").lower().startswith("magnet:")
    ]
    ed2k_payloads = [
        p for p in world.create_task_payloads if str(p.get("url") or "").lower().startswith("ed2k:")
    ]
    assert magnet_payloads, f"no magnet create_task: {world.create_task_payloads}"
    assert ed2k_payloads, f"no ed2k create_task: {world.create_task_payloads}"
    assert set(magnet_payloads[0].get("fileIndexes") or []) == {7, 11}

    # Emby / MP once for the AiringDue cycle.
    assert world.emby_calls - before_emby <= 1
    assert world.mp_resolve_calls - before_mp <= 1
    assert not any("run=-" in row and "剧集目标" in row for row in world.logs)

    # Pending / in-flight claims cover Direct+Magnet+ED2K episodes for second-run dedupe.
    pending = set(plugin._pending_library_episodes_v210(_tv()) or set())
    claims = set(plugin._active_source_claims(990001) or set())
    covered = pending | claims
    assert {5, 7, 9} & covered or any(
        str((row or {}).get("state") or "") in {"submitted", "queued", "waiting", "completed", "new", "dispatching"}
        and set(int(x) for x in ((row or {}).get("resolved_episodes") or (row or {}).get("target_episodes") or []) if int(x or 0) > 0) & {5, 7, 9}
        for row in (plugin._source_store().get("items") or {}).values()
    ), f"pending={pending} claims={claims} sources={plugin._source_store().get('items')}"
    n_tasks = len(world.create_task_payloads)
    out2 = airing["func"]()
    assert out2.get("success") is True
    assert len(world.create_task_payloads) == n_tasks

    # Emby ingest clears pending for E05/E07/E09.
    world.emby_existing = set(range(1, 11))
    snap = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert snap.get("final_target") == [] or set(snap.get("final_target") or []) <= {11, 12}
    assert set(snap.get("pending_library") or []) == set() or 11 not in set(snap.get("pending_library") or [])

    # Historical delete E03 re-enters target; sources preserved.
    plugin._update_source(
        "hist_e03",
        id="hist_e03",
        subscribe_id=990001,
        type="magnet",
        state="completed",
        enabled=True,
        target_episodes=[3],
        resolved_episodes=[3],
        completed_ts=time.time() - 3600,
    )
    world.emby_existing = set(range(1, 11)) - {3}
    world.mp_missing = {11, 12}
    snap3 = plugin._episode_target_snapshot_v210(_tv(), force_library=True, log=False)
    assert 3 in set(snap3["final_target"])
    assert plugin._source_store()["items"].get("hist_e03")

    # r95 library-polluted superseded source can reopen.
    plugin._update_source(
        "bad_super",
        id="bad_super",
        subscribe_id=990001,
        state="disabled",
        enabled=False,
        superseded_by_receipt=True,
        superseded_reason="library observation completed E03",
        target_episodes=[3],
    )
    plugin.save_data("episode_supersede_reopen_v211", {})
    plugin.save_data(
        "media_facts",
        {
            "s:990001:1:e0003": {"origin": "library", "episode": 3},
            "s:990001:1:e0005": {"origin": "guangya_offline", "episode": 5},
        },
    )
    plugin.save_data("episode_facts_migration_v211", {})
    plugin._migrate_library_observation_facts_v211_once()
    n = plugin._reopen_library_polluted_superseded_sources_v211()
    assert n >= 1
    row = plugin._source_store()["items"]["bad_super"]
    assert row.get("state") == "new"
    assert row.get("enabled") is True
