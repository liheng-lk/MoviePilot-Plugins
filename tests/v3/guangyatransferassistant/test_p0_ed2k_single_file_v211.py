"""P0: ED2K no-subfiles production — clear ambiguous, legitimate URI, video vs subtitle."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

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
make_final_plugin = _harness.make_final_plugin
load_final_plugin = _harness.load_final_plugin

LEGIT_MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
LEGIT_ED2K_VIDEO = (
    "ed2k://|file|光鸭测试剧.S01E09.1080p.mkv|1500000000|0123456789abcdef0123456789abcdef|/"
)
LEGIT_ED2K_SUB = (
    "ed2k://|file|光鸭测试剧.S01E09.zh-CN.ass|100000|abcdef0123456789abcdef0123456789|/"
)
LEGIT_ED2K_FUTURE = (
    "ed2k://|file|光鸭测试剧.S01E11.1080p.mkv|1500000000|fedcba9876543210fedcba9876543210|/"
)


def _tv():
    return SimpleNamespace(
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


def _wire_plugin(plugin, *, resolve_data):
    plugin._media_only = True
    plugin._episode_auto_confidence = 0.85
    plugin._quality_custom_reject_v1114 = ""
    plugin._quality_reject_low_tags_v1114 = True
    plugin._quality_require_subtitle_v1114 = False
    plugin._quality_min_resolution_v1114 = 720
    plugin._quality_min_video_mb_v1114 = 0
    plugin._is_movie_subscription = lambda s: False
    plugin._subscription_missing_episodes = lambda s: [5, 7, 9]
    plugin._authoritative_missing_v11214 = lambda s, current_source_id="": {5, 7, 9}
    plugin._pending_reservations = lambda s, exclude_job_key="": {
        "episodes": set(),
        "paths": set(),
        "movie": False,
    }
    plugin.save_data("sources", {"items": {}})
    plugin._source_store = lambda: plugin.get_data("sources") or {"items": {}}

    def _update_source(source_id, **fields):
        items = plugin._source_store()["items"]
        row = dict(items.get(str(source_id)) or {})
        row.update(fields)
        row["id"] = str(source_id)
        items[str(source_id)] = row
        plugin.save_data("sources", plugin._source_store())
        return row

    plugin._update_source = _update_source
    create_payloads = []

    def _offline_request(endpoint, payload):
        if "resolve" in str(endpoint):
            return {"success": True, "data": dict(resolve_data)}
        if "create_task" in str(endpoint):
            create_payloads.append(dict(payload or {}))
            return {"success": True, "data": {"taskId": f"ED2K_{len(create_payloads)}"}}
        return {"success": True, "data": {}}

    plugin._offline_request = _offline_request
    plugin._offline_api_success = lambda resp: bool((resp or {}).get("success"))
    plugin._offline_api_error = lambda resp, msg="err": msg
    plugin._offline_resolved_data = lambda resp: dict((resp or {}).get("data") or {})
    plugin._offline_target_parent = lambda subscribe: ("/media/光鸭测试剧", "parent1")
    plugin._create_payloads = create_payloads
    return plugin


def test_protocol_fixture_sanity_counts():
    load_final_plugin()
    from plugins.v3.guangyatransferassistant.source_types_v180 import (
        normalize_ed2k,
        normalize_magnet,
    )
    from plugins.v3.guangyatransferassistant.provider_sources_v192 import _find_links

    assert normalize_magnet(LEGIT_MAGNET)["type"] == "magnet"
    assert normalize_ed2k(LEGIT_ED2K_VIDEO)["name"].endswith(".mkv")
    assert normalize_ed2k(LEGIT_ED2K_SUB)["name"].endswith(".ass")
    found = _find_links(
        "\n".join([LEGIT_MAGNET, LEGIT_ED2K_VIDEO, LEGIT_ED2K_SUB]),
        name="光鸭测试剧",
        provider="viewing",
    )
    magnets = [r for r in found if str(r.get("uri") or "").lower().startswith("magnet:")]
    ed2ks = [r for r in found if str(r.get("uri") or "").lower().startswith("ed2k://")]
    assert len(magnets) == 1
    assert len(ed2ks) == 2


def test_ed2k_video_selection_clears_ambiguous():
    plugin = _wire_plugin(
        make_final_plugin(),
        resolve_data={
            "url": LEGIT_ED2K_VIDEO,
            "btResInfo": {"fileName": "光鸭测试剧.S01E09.1080p.mkv", "subfiles": []},
        },
    )
    source = {
        "id": "ed2k_v",
        "type": "ed2k",
        "uri": LEGIT_ED2K_VIDEO,
        "name": "光鸭测试剧.S01E09.1080p.mkv",
        "target_episodes": [9],
        "episode_hint": "E09",
    }
    sel = plugin._planner_file_selection(source, _tv(), {
        "url": LEGIT_ED2K_VIDEO,
        "btResInfo": {"fileName": "光鸭测试剧.S01E09.1080p.mkv", "subfiles": []},
    })
    assert sel.get("ambiguous") is False
    assert sel.get("episodes") == [9]
    assert sel.get("ed2k_single_file") is True


def test_ed2k_subtitle_blocked_selected_video_missing():
    plugin = _wire_plugin(
        make_final_plugin(),
        resolve_data={
            "url": LEGIT_ED2K_SUB,
            "btResInfo": {"fileName": "光鸭测试剧.S01E09.zh-CN.ass", "subfiles": []},
        },
    )
    source = {
        "id": "ed2k_s",
        "type": "ed2k",
        "uri": LEGIT_ED2K_SUB,
        "name": "光鸭测试剧.S01E09.zh-CN.ass",
        "target_episodes": [9],
    }
    try:
        plugin._resolve_offline_source(source, _tv())
        assert False, "expected RuntimeError"
    except RuntimeError as err:
        assert "SELECTED_VIDEO_MISSING" in str(err)


def test_ed2k_out_of_target_future_blocked():
    plugin = _wire_plugin(
        make_final_plugin(),
        resolve_data={
            "url": LEGIT_ED2K_FUTURE,
            "btResInfo": {"fileName": "光鸭测试剧.S01E11.1080p.mkv", "subfiles": []},
        },
    )
    source = {
        "id": "ed2k_f",
        "type": "ed2k",
        "uri": LEGIT_ED2K_FUTURE,
        "name": "光鸭测试剧.S01E11.1080p.mkv",
        "target_episodes": [9],
    }
    sel = plugin._planner_file_selection(source, _tv(), {
        "url": LEGIT_ED2K_FUTURE,
        "btResInfo": {"fileName": "光鸭测试剧.S01E11.1080p.mkv", "subfiles": []},
    })
    assert sel.get("out_of_target") is True
    assert sel.get("ambiguous") is False
    assert not sel.get("episodes")
    try:
        plugin._resolve_offline_source(source, _tv())
        assert False, "expected RuntimeError"
    except RuntimeError as err:
        assert "EPISODE_NOT_TARGET" in str(err) or "NOT_TARGET" in str(err)


def test_ed2k_resolve_submit_create_task():
    plugin = _wire_plugin(
        make_final_plugin(),
        resolve_data={
            "url": LEGIT_ED2K_VIDEO,
            "btResInfo": {"fileName": "光鸭测试剧.S01E09.1080p.mkv", "subfiles": []},
        },
    )
    subscribe = _tv()
    plugin._find_subscription = lambda sid: subscribe if int(sid or 0) == 990001 else None
    plugin._list_subscriptions = lambda: [subscribe]
    source = {
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
    plugin._update_source("ed2k_v", **source)
    resolved = plugin._resolve_offline_source(source, subscribe)
    assert resolved.get("selected_indexes") == []
    row = plugin._source_store()["items"]["ed2k_v"]
    assert list(row.get("resolved_episodes") or []) == [9]
    assert row.get("state") != "needs_review"
    plugin._final_target_allows_submit_v211 = lambda s, eps: (True, set(eps or [9]), "test")
    plugin._mark_pending_library_confirmation_v210 = lambda *a, **k: None
    out = plugin._submit_offline_source("ed2k_v")
    assert plugin._create_payloads, f"no create_task: {out}"
    assert plugin._source_store()["items"]["ed2k_v"].get("state") != "needs_review"
