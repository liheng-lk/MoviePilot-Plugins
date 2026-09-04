from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GATE = PLUGIN / "resource_gate_v1127.py"
IDENTITY = PLUGIN / "media_identity_v1111.py"
ENTRY = PLUGIN / "__init__.py"


def _gate_class():
    identity_ns: Dict[str, Any] = {}
    exec(compile(IDENTITY.read_text(encoding="utf-8"), str(IDENTITY), "exec"), identity_ns)

    tree = ast.parse(GATE.read_text(encoding="utf-8"), filename=str(GATE))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaResourceGateV1127Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "Sequence": Sequence,
        "Set": Set,
        "Tuple": Tuple,
        "time": time,
        "_subscription_aliases": lambda subscribe: list(getattr(subscribe, "aliases", []) or []),
    }
    for name in (
        "any_alias_title_match_v1111",
        "assess_media_identity_v1111",
        "explicit_seasons_v1111",
        "explicit_years_v1111",
        "has_episode_structure_v1111",
        "strong_title_match_v1111",
        "title_variants_v1111",
    ):
        ns[name] = identity_ns[name]
    exec(compile(module, str(GATE), "exec"), ns)
    return ns["GuangYaResourceGateV1127Mixin"]


class _Base:
    def _provider_candidate_matches(self, subscribe, row):
        return False

    def _xunlei_json_identity_matches_v1123(self, subscribe, candidate, info, template):
        return False, "legacy hard reject"

    def _planner_file_selection(self, source, subscribe, resolve_data):
        return {"indexes": [8, 9], "episodes": [9, 10], "ambiguous": False}

    def _mark_offline_failure(self, source, error, *, attempt_increment=True):
        return {**dict(source), "state": "needs_review", "last_error": str(error)}

    def _existing_source(self, subscribe_id, source_type, identity):
        return dict(self.existing)


Mixin = _gate_class()


class _Probe(Mixin, _Base):
    def __init__(self, subscribe):
        self.subscribe = subscribe
        self.logs = []
        self.existing = {}
        self.persisted = {}
        self.reserved = set()

    def _is_movie_subscription(self, subscribe):
        return bool(getattr(subscribe, "is_movie", False))

    def _identity_aliases_v1111(self, subscribe):
        return list(getattr(subscribe, "aliases", []) or [])

    def _plugin_log(self, level, message, *args):
        self.logs.append((level, message % args if args else message))

    def _subscription_missing_episodes(self, subscribe):
        return list(getattr(subscribe, "missing", []) or [])

    def _pending_reservations(self, subscribe):
        return {"episodes": set(self.reserved), "paths": set(), "movie": False}

    def _find_subscription(self, sid):
        return self.subscribe if int(sid or 0) == int(getattr(self.subscribe, "id", 0) or 0) else None

    def _update_source(self, source_id, **fields):
        row = dict(self.existing or {"id": source_id, "subscribe_id": self.subscribe.id})
        row.update(fields)
        self.existing = row
        self.persisted = dict(row)
        return row

    def _now_text(self):
        return "2026-09-05 00:00:00"


def _tv(name, year, season, aliases, missing=(9, 10)):
    return SimpleNamespace(
        id=100,
        name=name,
        year=year,
        season=season,
        aliases=list(aliases),
        missing=list(missing),
        total_episode=10,
        is_movie=False,
        type="电视剧",
    )


def test_v1127_layer_parses_and_is_outer_runtime_gate():
    gate_text = GATE.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    ast.parse(gate_text, filename=str(GATE))
    assert 'plugin_version = "1.12.7"' in gate_text
    assert 'build_id = "20260905-r53"' in gate_text
    assert "GuangYaResourceGateV1127Mixin" in entry
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaResourceGateV1127Mixin") < head.index("GuangYaFastRecallV1126Mixin")


def test_severance_s02_season_release_year_is_not_rejected_as_series_year_conflict():
    subscribe = _tv("人生切割术", 2022, 2, ["人生切割术", "Severance"])
    probe = _Probe(subscribe)
    candidate = {"search_title": "Severance", "name": "Severance S02 2025"}
    assert probe._provider_candidate_matches(subscribe, candidate) is True

    ok, reason = probe._xunlei_json_identity_matches_v1123(
        subscribe,
        candidate,
        {"title": "Severance Season 2 2025"},
        {"files": [
            {"path": "Severance.S02E09.2025.1080p.WEB-DL.mkv"},
            {"path": "Severance.S02E10.2025.1080p.WEB-DL.mkv"},
        ]},
    )
    assert ok is True
    assert "季发行年份桥接" in reason


def test_wrong_season_and_movie_wrong_year_are_never_rescued():
    subscribe = _tv("人生切割术", 2022, 2, ["人生切割术", "Severance"])
    probe = _Probe(subscribe)
    candidate = {"search_title": "Severance", "name": "Severance S03 2025"}
    assert probe._provider_candidate_matches(subscribe, candidate) is False
    ok, _ = probe._xunlei_json_identity_matches_v1123(
        subscribe,
        candidate,
        {"title": "Severance Season 3 2025"},
        {"files": [{"path": "Severance.S03E01.2025.mkv"}]},
    )
    assert ok is False

    movie = SimpleNamespace(
        id=101, name="Demo", year=2024, season=0, aliases=["Demo"], missing=[],
        total_episode=0, is_movie=True, type="电影",
    )
    movie_probe = _Probe(movie)
    ok, _ = movie_probe._xunlei_json_identity_matches_v1123(
        movie,
        {"search_title": "Demo", "name": "Demo 2025"},
        {"title": "Demo 2025"},
        {"files": [{"path": "Demo.2025.1080p.mkv"}]},
    )
    assert ok is False


def test_first_season_wrong_year_is_not_treated_as_season_release_year():
    subscribe = _tv("炒翻天", 2026, 1, ["炒翻天", "鉄鍋のジャン"])
    probe = _Probe(subscribe)
    ok, _ = probe._xunlei_json_identity_matches_v1123(
        subscribe,
        {"search_title": "炒翻天", "name": "铁锅料理王 S01 2025"},
        {"title": "铁锅料理王 S01 2025"},
        {"files": [{"path": "铁锅料理王.S01E09.2025.1080p.mkv"}]},
    )
    assert ok is False


def test_tetsunabe_legitimate_alias_bridge_requires_discovery_season_year_and_file_consistency():
    subscribe = _tv("炒翻天", 2026, 1, ["炒翻天", "鉄鍋のジャン"], missing=(9,))
    probe = _Probe(subscribe)
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        subscribe,
        {"search_title": "炒翻天", "name": "铁锅料理王 S01 2026"},
        {"title": "铁锅料理王 S01 2026"},
        {"files": [{"path": "铁锅料理王.S01E09.2026.1080p.WEB-DL.mkv"}]},
    )
    assert ok is True
    assert "合法别名桥接" in reason

    # 搜索发现标题若不是订阅别名，即使真实包内部自洽也不能桥接。
    ok, _ = probe._xunlei_json_identity_matches_v1123(
        subscribe,
        {"search_title": "别的动画", "name": "铁锅料理王 S01 2026"},
        {"title": "铁锅料理王 S01 2026"},
        {"files": [{"path": "铁锅料理王.S01E09.2026.mkv"}]},
    )
    assert ok is False


def test_planner_observability_reports_real_missing_reserved_target_and_indexes():
    subscribe = _tv("人生切割术", 2022, 2, ["人生切割术", "Severance"])
    probe = _Probe(subscribe)
    probe.reserved = {9}
    result = probe._planner_file_selection(
        {"type": "xunlei", "target_episodes": [9, 10]},
        subscribe,
        {"btResInfo": {"subfiles": []}},
    )
    assert result["indexes"] == [8, 9]
    line = next(text for _, text in probe.logs if "【拆包v1.12.7】" in text)
    assert "missing=[9, 10]" in line
    assert "reserved=[9]" in line
    assert "target=[10]" in line
    assert "resolved=[9, 10]" in line
    assert "indexes=[8, 9]" in line


def test_needs_review_reopens_once_for_legacy_or_changed_evidence_but_not_every_ten_minutes():
    subscribe = _tv("人生切割术", 2022, 2, ["人生切割术", "Severance"])
    probe = _Probe(subscribe)
    probe.existing = {
        "id": "src-1", "subscribe_id": 100, "state": "needs_review",
        "target_episodes": [9, 10], "episode_hint": "S02E09-E10",
    }

    reopened = probe._existing_source(100, "magnet", "abc")
    assert reopened["state"] == "review_reopen"
    assert probe.persisted["state"] == "new"

    # 模拟再次拆包仍歧义：记录当前证据后，不应被 10 分钟 AiringDue 无限重启。
    probe.existing = {
        **probe.persisted,
        "state": "needs_review",
        "review_fingerprint_v1127": probe._review_fingerprint_v1127(subscribe, probe.persisted),
        "review_at_v1127": time.time(),
    }
    stable = probe._existing_source(100, "magnet", "abc")
    assert stable["state"] == "needs_review"

    subscribe.missing = [10]
    changed = probe._existing_source(100, "magnet", "abc")
    assert changed["state"] == "review_reopen"
    assert probe.persisted["state"] == "new"


def test_needs_review_same_evidence_can_be_rechecked_after_six_hours():
    subscribe = _tv("Demo", 2026, 1, ["Demo"], missing=(3,))
    probe = _Probe(subscribe)
    source = {"id": "src-2", "subscribe_id": 100, "state": "needs_review", "target_episodes": [3]}
    source["review_fingerprint_v1127"] = probe._review_fingerprint_v1127(subscribe, source)
    source["review_at_v1127"] = time.time() - (6 * 60 * 60 + 1)
    probe.existing = source
    reopened = probe._existing_source(100, "magnet", "def")
    assert reopened["state"] == "review_reopen"
    assert "6 小时" in str(probe.persisted.get("review_reopen_reason_v1127") or "")


def test_v1127_public_metadata_keeps_v1126_history():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == plugin["version"] == "1.12.8"
    assert "v1.12.7" in package["history"]
    assert "v1.12.6" in package["history"]
    entry = ENTRY.read_text(encoding="utf-8")
    assert 'plugin_version = "1.12.8"' in entry
    assert 'build_id = "20260905-r54"' in entry
