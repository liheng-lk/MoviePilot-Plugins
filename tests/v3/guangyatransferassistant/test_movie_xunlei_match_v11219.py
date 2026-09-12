import ast
from pathlib import Path
from typing import Any, Dict, Tuple


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE_PATH = PLUGIN / "media_match_v11219.py"
FAST_PATH = PLUGIN / "fast_recall_v1126.py"
ENTRY_PATH = PLUGIN / "__init__.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
FAST = FAST_PATH.read_text(encoding="utf-8")
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _mixin_class(movie_match):
    tree = ast.parse(SOURCE)
    source_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaMediaMatchV11219Mixin"
    )
    method = next(
        node for node in source_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_xunlei_json_identity_matches_v1123"
    )
    probe_class = ast.ClassDef(
        name="GuangYaMovieXunleiMatchProbeMixin",
        bases=[],
        keywords=[],
        body=[method],
        decorator_list=[],
    )
    module = ast.Module(body=[probe_class], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Tuple": Tuple,
        "_is_video": lambda value: str(value or "").lower().endswith((".mkv", ".mp4", ".avi", ".ts")),
        "movie_actual_match_v11219": movie_match,
    }
    exec(compile(module, str(SOURCE_PATH), "exec"), ns)
    return ns["GuangYaMovieXunleiMatchProbeMixin"]


class _Base:
    parent_result = (True, "parent accepted")

    def _xunlei_json_identity_matches_v1123(self, subscribe, candidate, info, template):
        return self.parent_result

    def _is_movie_subscription(self, subscribe):
        return bool(subscribe.get("movie"))

    def _identity_aliases_v1111(self, subscribe):
        return list(subscribe.get("aliases") or [subscribe.get("name") or "Movie"])

    def _bilingual_bridge_v11216(self, subscribe, candidate, info, template):
        return bool(subscribe.get("bridge")), "strict bilingual bridge"


def _probe(movie_match):
    mixin = _mixin_class(movie_match)

    class Probe(mixin, _Base):
        pass

    return Probe()


def test_xunlei_movie_match_is_wired_after_general_media_match():
    assert "from .media_match_v11219 import GuangYaMediaMatchV11219Mixin" in FAST
    assert "GuangYaMovieXunleiMatchV11219Mixin" not in FAST
    assert not (PLUGIN / "movie_xunlei_match_v11219.py").exists()
    assert 'plugin_version = "2.0.13"' in ENTRY


def test_parent_rejection_remains_rejected_without_rescue():
    calls = []
    probe = _probe(lambda **kwargs: calls.append(kwargs) or {"ok": True})
    probe.parent_result = (False, "existing hard conflict")
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        {"movie": True},
        {},
        {},
        {"files": [{"path": "Movie.2026.mkv"}]},
    )
    assert ok is False
    assert reason == "existing hard conflict"
    assert calls == []


def test_series_keeps_existing_xunlei_identity_chain_unchanged():
    calls = []
    probe = _probe(lambda **kwargs: calls.append(kwargs) or {"ok": False})
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        {"movie": False},
        {},
        {},
        {"files": [{"path": "Show.S01E01.mkv"}]},
    )
    assert ok is True
    assert reason == "parent accepted"
    assert calls == []


def test_movie_requires_real_video_in_xunlei_json_payload():
    probe = _probe(lambda **kwargs: {"ok": True})
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        {"movie": True, "aliases": ["Movie"]},
        {},
        {"title": "Movie 2026"},
        {"files": [{"path": "Movie.2026.srt"}]},
    )
    assert ok is False
    assert "未发现可验证的视频文件" in reason


def test_movie_actual_gate_uses_real_title_and_video_not_search_title():
    calls = []

    def matcher(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "score": 80, "reason": "actual matched"}

    probe = _probe(matcher)
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        {"movie": True, "aliases": ["Real Movie"], "year": 2026},
        {"search_title": "Search Card", "name": "Search Card"},
        {"title": "Real Movie 2026"},
        {"files": [
            {"path": "Real.Movie.2026.1080p.mkv"},
            {"path": "Search.Card.poster.jpg"},
        ]},
    )
    assert ok is True
    assert "真实 payload 通过" in reason
    assert len(calls) == 1
    assert calls[0]["primary_evidences"] == ["Real Movie 2026", ""]
    assert calls[0]["file_evidences"] == ["Real.Movie.2026.1080p.mkv"]


def test_strict_bilingual_real_resource_bridge_is_preserved():
    probe = _probe(lambda **kwargs: {"ok": False, "reason": "official alias miss"})
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        {"movie": True, "bridge": True, "aliases": ["中文片名"]},
        {"search_title": "中文片名", "name": "中文片名 English Title"},
        {"title": "中文片名 English Title 2026"},
        {"files": [{"path": "English.Title.2026.mkv"}]},
    )
    assert ok is True
    assert "双语闭环通过" in reason


def test_movie_rejected_when_actual_gate_and_strict_bridge_both_fail():
    probe = _probe(lambda **kwargs: {"ok": False, "reason": "wrong actual movie"})
    ok, reason = probe._xunlei_json_identity_matches_v1123(
        {"movie": True, "bridge": False, "aliases": ["Expected Movie"]},
        {"search_title": "Expected Movie"},
        {"title": "Other Movie 2026"},
        {"files": [{"path": "Other.Movie.2026.mkv"}]},
    )
    assert ok is False
    assert "真实 payload 身份拒绝" in reason
    assert "wrong actual movie" in reason

