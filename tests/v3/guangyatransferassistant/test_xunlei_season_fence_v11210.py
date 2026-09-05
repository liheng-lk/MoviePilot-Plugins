from __future__ import annotations

import ast
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "xunlei_season_fence_v11210.py"
MOVIE_IDENTITY = PLUGIN / "movie_identity_v1129.py"
ENTRY = PLUGIN / "__init__.py"


def _explicit_seasons(values: Iterable[Any]) -> Set[int]:
    result: Set[int] = set()
    for raw in values or []:
        text = str(raw or "")
        for token in re.findall(r"(?i)(?:S|Season[ ._-]*)0*(\d{1,2})(?=E|[^0-9]|$)", text):
            result.add(int(token))
        for token in re.findall(r"第\s*(\d{1,2})\s*季", text):
            result.add(int(token))
    return result


def _resolve_episode(path: str, **kwargs) -> Dict[str, Any]:
    text = str(path or "").replace("\\", "/")
    matched = re.search(r"(?i)S\d{1,2}[ ._-]*E0*(\d{1,4})", text)
    if matched:
        return {"episodes": [int(matched.group(1))], "confidence": 1.0}
    name = text.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    matched = re.fullmatch(r"0*(\d{1,4})", name)
    if matched:
        return {"episodes": [int(matched.group(1))], "confidence": 1.0}
    return {"episodes": [], "confidence": 0.0}


def _reliable(result: Dict[str, Any], threshold: float) -> Set[int]:
    return {int(value) for value in (result.get("episodes") or []) if int(value or 0) > 0}


def _mixin_class():
    tree = ast.parse(PATCH.read_text(encoding="utf-8"), filename=str(PATCH))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaXunleiSeasonFenceV11210Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Optional": Optional,
        "Set": Set,
        "Tuple": Tuple,
        "threading": threading,
        "time": time,
        "re": re,
        "AUTO_SELECT_CONFIDENCE": 0.90,
        "resolve_episode": _resolve_episode,
        "reliable_episode_set": _reliable,
        "explicit_seasons_v1111": _explicit_seasons,
        "_is_video": lambda path: str(path or "").lower().endswith((".mp4", ".mkv")),
        "is_auxiliary_media_v1105": lambda path: False,
    }
    exec(compile(module, str(PATCH), "exec"), ns)
    return ns["GuangYaXunleiSeasonFenceV11210Mixin"]


class _Base:
    def _xunlei_json_identity_matches_v1123(self, subscribe, candidate, info, template):
        return True, "parent identity accepted"

    def _save_xunlei_state(self, state):
        self.base_save_calls += 1

    def _dispatch_xunlei_flash(self, subscribe):
        with self.activity_guard:
            self.activity += 1
            self.max_activity = max(self.max_activity, self.activity)
        try:
            time.sleep(0.03)
            return {"success": True, "handled": True}
        finally:
            with self.activity_guard:
                self.activity -= 1


class _Probe(_mixin_class(), _Base):
    def __init__(self, backend=None, subscriptions=None):
        self.backend = backend if backend is not None else {}
        self.subscriptions = subscriptions if subscriptions is not None else {}
        self.logs = []
        self.base_save_calls = 0
        self.activity = 0
        self.max_activity = 0
        self.activity_guard = threading.Lock()
        self._episode_auto_confidence = 0.90

    def get_data(self, key):
        return self.backend.get(key)

    def save_data(self, key, value):
        self.backend[key] = value

    def _find_subscription(self, sid):
        return self.subscriptions.get(int(sid or 0))

    @staticmethod
    def _is_movie_subscription(subscribe):
        return str(getattr(subscribe, "type", "") or "").lower() in {"movie", "电影"}

    @staticmethod
    def _media_fact_prefix(subscribe):
        source = str(getattr(getattr(subscribe, "media_source", None), "value", "tmdb") or "tmdb")
        media_id = str(getattr(subscribe, "media_id", "") or "")
        season = int(getattr(subscribe, "season", 1) or 1)
        return f"{source}:{media_id}:s{season:02d}"

    def _xunlei_state(self):
        state = self.backend.get("xunlei_flash_state") or {"schema": 1, "items": {}}
        return state

    def _plugin_log(self, level, message, *args):
        self.logs.append((level, message % args if args else message))


def _tv(sid: int, season: int, total: int, *, media_id="70030"):
    return SimpleNamespace(
        id=sid,
        name="大唐荣耀",
        year=2017,
        type="tv",
        season=season,
        total_episode=total,
        media_source=SimpleNamespace(value="tmdb"),
        media_id=str(media_id),
    )


def _movie():
    return SimpleNamespace(
        id=900,
        name="电影",
        year=2017,
        type="movie",
        season=0,
        total_episode=0,
        media_source=SimpleNamespace(value="tmdb"),
        media_id="99",
    )


def _template(count: int, *, prefix="大唐荣耀（2017）"):
    return {
        "shareId": "VOTVbXVkEJ_4jd3Wud7YbC8w",
        "files": [
            {"path": f"{prefix}/{index:02d}.mp4", "size": 1000 + index}
            for index in range(count, 0, -1)
        ],
    }


def _candidate():
    return {"share_id": "VOTVbXVkEJ_4jd3Wud7YbC8w", "search_title": "大唐荣耀"}


def test_v11210_source_parses_and_is_between_movie_identity_and_resource_gate():
    patch = PATCH.read_text(encoding="utf-8")
    movie = MOVIE_IDENTITY.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    ast.parse(patch, filename=str(PATCH))
    ast.parse(movie, filename=str(MOVIE_IDENTITY))
    assert 'plugin_version = "1.12.10"' in patch
    assert 'build_id = "20260905-r56"' in patch
    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
    ast.parse(manual, filename=str(PLUGIN / "manual_check_v11211.py"))
    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in movie
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie
    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in manual
    assert "class GuangYaManualCheckV11211Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in manual
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaResourceGateV1127Mixin")


def test_datang_s02_rejects_seasonless_60_episode_s01_package_before_import():
    sub = _tv(241, 2, 32)
    probe = _Probe(subscriptions={241: sub})
    accepted, reason = probe._xunlei_json_identity_matches_v1123(sub, _candidate(), {}, _template(60))
    assert accepted is False
    assert "订阅 S02 共32集" in reason
    assert "实际包解析到 E60" in reason
    assert "禁止裁剪" in reason


def test_datang_s01_accepts_matching_60_episode_seasonless_package():
    sub = _tv(240, 1, 60)
    probe = _Probe(subscriptions={240: sub})
    accepted, reason = probe._xunlei_json_identity_matches_v1123(sub, _candidate(), {}, _template(60))
    assert accepted is True
    assert reason == "parent identity accepted"


def test_explicit_s02_package_is_left_to_existing_identity_and_planner():
    sub = _tv(241, 2, 32)
    probe = _Probe(subscriptions={241: sub})
    accepted, _ = probe._xunlei_json_identity_matches_v1123(
        sub,
        _candidate(),
        {},
        _template(32, prefix="大唐荣耀/S02"),
    )
    assert accepted is True


def test_explicit_multiseason_package_bypasses_seasonless_share_claim():
    s1 = _tv(240, 1, 10)
    s2 = _tv(241, 2, 10)
    backend = {}
    probe = _Probe(backend=backend, subscriptions={240: s1, 241: s2})
    probe._xunlei_write_success_claim_v11210(s1, _candidate()["share_id"], "大唐荣耀/01.mp4")
    template = {
        "shareId": _candidate()["share_id"],
        "files": [
            {"path": "大唐荣耀/S01/S01E01.mp4", "size": 1000},
            {"path": "大唐荣耀/S02/S02E01.mp4", "size": 1000},
        ],
    }
    accepted, reason = probe._xunlei_json_identity_matches_v1123(s2, _candidate(), {}, template)
    assert accepted is True, reason


def test_successful_seasonless_share_claim_blocks_other_season_even_when_counts_match():
    s1 = _tv(240, 1, 10)
    s2 = _tv(241, 2, 10)
    backend = {}
    probe = _Probe(backend=backend, subscriptions={240: s1, 241: s2})
    state = {
        "schema": 1,
        "items": {
            "a": {
                "state": "completed",
                "subscribe_id": 240,
                "share_id": _candidate()["share_id"],
                "path": "大唐荣耀（2017）/01.mp4",
                "updated_ts": 100.0,
            }
        },
    }
    probe._save_xunlei_state(state)
    assert probe.base_save_calls == 1
    accepted, reason = probe._xunlei_json_identity_matches_v1123(s2, _candidate(), {}, _template(10))
    assert accepted is False
    assert "S01 / 订阅#240" in reason
    assert "S02 / 订阅#241" in reason


def test_same_subscription_retry_is_idempotent_after_claim():
    s1 = _tv(240, 1, 10)
    backend = {}
    probe = _Probe(backend=backend, subscriptions={240: s1})
    probe._xunlei_write_success_claim_v11210(s1, _candidate()["share_id"], "大唐荣耀/01.mp4")
    accepted, reason = probe._xunlei_json_identity_matches_v1123(s1, _candidate(), {}, _template(10))
    assert accepted is True, reason


def test_persisted_claim_survives_new_plugin_instance():
    s1 = _tv(240, 1, 10)
    s2 = _tv(241, 2, 10)
    shared = {}
    first = _Probe(backend=shared, subscriptions={240: s1, 241: s2})
    first._xunlei_write_success_claim_v11210(s1, _candidate()["share_id"], "大唐荣耀/01.mp4")
    second = _Probe(backend=shared, subscriptions={240: s1, 241: s2})
    accepted, reason = second._xunlei_json_identity_matches_v1123(s2, _candidate(), {}, _template(10))
    assert accepted is False
    assert "同一无季号迅雷分享已由本系列" in reason


def test_pre_v11210_completed_xunlei_state_is_recovered_as_claim():
    s1 = _tv(240, 1, 10)
    s2 = _tv(241, 2, 10)
    shared = {
        "xunlei_flash_state": {
            "schema": 1,
            "items": {
                "legacy": {
                    "state": "completed",
                    "subscribe_id": 240,
                    "share_id": _candidate()["share_id"],
                    "path": "大唐荣耀（2017）/01.mp4",
                    "updated_ts": 50.0,
                }
            },
        }
    }
    probe = _Probe(backend=shared, subscriptions={240: s1, 241: s2})
    accepted, reason = probe._xunlei_json_identity_matches_v1123(s2, _candidate(), {}, _template(10))
    assert accepted is False
    assert "订阅#240" in reason
    claims = shared.get("xunlei_share_season_claims_v11210") or {}
    assert (claims.get("items") or {})


def test_movies_are_untouched_by_tv_season_fence():
    movie = _movie()
    probe = _Probe(subscriptions={900: movie})
    accepted, reason = probe._xunlei_json_identity_matches_v1123(movie, _candidate(), {}, _template(60))
    assert accepted is True
    assert reason == "parent identity accepted"


def test_same_series_xunlei_dispatch_is_serialized_across_seasons():
    s1 = _tv(240, 1, 10)
    s2 = _tv(241, 2, 10)
    probe = _Probe(subscriptions={240: s1, 241: s2})
    start = threading.Event()

    def worker(sub):
        start.wait(timeout=1)
        probe._dispatch_xunlei_flash(sub)

    threads = [threading.Thread(target=worker, args=(s1,)), threading.Thread(target=worker, args=(s2,))]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=2)
    assert all(not thread.is_alive() for thread in threads)
    assert probe.max_activity == 1


def test_v11210_does_not_change_provider_priority_or_media_business_policy():
    text = PATCH.read_text(encoding="utf-8")
    for forbidden in (
        "provider_priority",
        "Magnet >",
        "target_directory",
        "rename_format",
        "SubscribeChain",
        "create_subscription",
        "delete_subscription",
    ):
        assert forbidden not in text, forbidden
