from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE = PLUGIN / "movie_bilingual_identity_v11216.py"
MOVIE_IDENTITY = PLUGIN / "movie_identity_v1129.py"
MEDIA_IDENTITY = PLUGIN / "media_identity_v1111.py"


def _media_namespace():
    spec = importlib.util.spec_from_file_location("guangya_media_identity_v1111_test", MEDIA_IDENTITY)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


MEDIA = _media_namespace()


class _Base:
    reject_reason = "迅雷实际资源身份拒绝：实际资源顶层标题与订阅不一致：legacy"

    def __init__(self):
        self.logs = []

    @staticmethod
    def _identity_is_movie_v1111(subscribe):
        raw = str(getattr(subscribe, "type", "") or "")
        return "电影" in raw or "movie" in raw.lower()

    @staticmethod
    def _identity_aliases_v1111(subscribe):
        return [str(getattr(subscribe, "name", "") or "")]

    def _xunlei_json_identity_matches_v1123(self, subscribe, candidate, info, template):
        return False, self.reject_reason

    def _plugin_log(self, *args):
        self.logs.append(args)


def _namespace():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level:
            continue
        body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "GuangYaManualCheckV11211Mixin": _Base,
        "explicit_seasons_v1111": MEDIA.explicit_seasons_v1111,
        "explicit_years_v1111": MEDIA.explicit_years_v1111,
        "strong_title_match_v1111": MEDIA.strong_title_match_v1111,
        "title_key_v1111": MEDIA.title_key_v1111,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


NS = _namespace()
Probe = NS["GuangYaMovieBilingualIdentityV11216Mixin"]
segments = NS["_title_segments_v11216"]


def _subscribe(year="2026", mtype="电影"):
    return SimpleNamespace(id=174, name="荣光与暗影", year=year, type=mtype)


def _template(path="Les.rayons.et.les.ombres.2026.READNFO.FRENCH.1080p.WEB.H264-PiCKLES.mkv"):
    return {"files": [{"path": path, "size": 123456789}]}


def test_bilingual_title_segments_extract_exact_chinese_and_french_sides():
    keys = {key for key, _ in segments("🌈荣光与暗影 Les rayons et les ombres (2026)", "2026")}
    assert MEDIA.title_key_v1111("荣光与暗影", expected_year="2026") in keys
    assert MEDIA.title_key_v1111("Les rayons et les ombres", expected_year="2026") in keys


def test_real_log_case_is_rescued_only_by_same_share_bilingual_closed_loop():
    probe = Probe()
    accepted, reason = probe._xunlei_json_identity_matches_v1123(
        _subscribe(),
        {
            "search_title": "荣光与暗影",
            "name": "🌈荣光与暗影 Les rayons et les ombres (2026)",
            "label": "荣光与暗影",
        },
        {"title": "Les.rayons.et.les.ombres.2026.READNFO.FRENCH.1080p.WEB.H264-PiCKLES.mkv"},
        _template(),
    )
    assert accepted is True
    assert "双语" in reason
    assert "Les rayons et les ombres" in reason
    assert probe.logs and "电影双语身份v1.12.16" in str(probe.logs[-1])


def test_decorated_panlist_label_does_not_break_bilingual_bridge():
    probe = Probe()
    accepted, reason = probe._xunlei_json_identity_matches_v1123(
        _subscribe(),
        {
            "search_title": "荣光与暗影",
            "name": "⭐⭐⭐---【荣光与暗影】【剧情/传记】---",
            "label": "荣光与暗影",
        },
        {"title": "🌈荣光与暗影 Les rayons et les ombres (2026)"},
        _template(),
    )
    assert accepted is True
    assert "Les rayons et les ombres" in reason


def test_pure_foreign_file_without_same_share_bilingual_bridge_remains_rejected():
    probe = Probe()
    accepted, reason = probe._xunlei_json_identity_matches_v1123(
        _subscribe(),
        {"search_title": "荣光与暗影", "name": "荣光与暗影", "label": "荣光与暗影"},
        {"title": "Les.rayons.et.les.ombres.2026.1080p.WEB.mkv"},
        _template(),
    )
    assert accepted is False
    assert "顶层标题与订阅不一致" in reason


def test_wrong_actual_movie_remains_hard_rejected_even_when_discovery_matches():
    probe = Probe()
    accepted, _ = probe._xunlei_json_identity_matches_v1123(
        _subscribe(),
        {"search_title": "荣光与暗影", "name": "Other Film (2026)", "label": "荣光与暗影"},
        {"title": "Other.Film.2026.1080p.WEB.mkv"},
        {"files": [{"path": "Other.Film.2026.1080p.WEB.mkv", "size": 100}]},
    )
    assert accepted is False


def test_wrong_year_never_uses_bilingual_bridge():
    probe = Probe()
    accepted, _ = probe._xunlei_json_identity_matches_v1123(
        _subscribe(year="2026"),
        {"search_title": "荣光与暗影", "name": "🌈荣光与暗影 Les rayons et les ombres (2025)"},
        {"title": "Les.rayons.et.les.ombres.2025.1080p.WEB.mkv"},
        {"files": [{"path": "Les.rayons.et.les.ombres.2025.1080p.WEB.mkv", "size": 100}]},
    )
    assert accepted is False


def test_tv_never_uses_movie_bilingual_bridge():
    probe = Probe()
    accepted, _ = probe._xunlei_json_identity_matches_v1123(
        _subscribe(mtype="电视剧"),
        {"search_title": "荣光与暗影", "name": "🌈荣光与暗影 Les rayons et les ombres (2026)"},
        {"title": "Les.rayons.et.les.ombres.2026.S01E01.mkv"},
        {"files": [{"path": "Les.rayons.et.les.ombres.2026.S01E01.mkv", "size": 100}]},
    )
    assert accepted is False


def test_non_title_conflict_is_never_rescued():
    probe = Probe()
    probe.reject_reason = "迅雷实际资源身份拒绝：实际资源年份冲突：期望=2026 实际=2025"
    accepted, reason = probe._xunlei_json_identity_matches_v1123(
        _subscribe(),
        {"search_title": "荣光与暗影", "name": "🌈荣光与暗影 Les rayons et les ombres (2026)"},
        {"title": "Les.rayons.et.les.ombres.2026.mkv"},
        _template("Les.rayons.et.les.ombres.2026.mkv"),
    )
    assert accepted is False
    assert "年份冲突" in reason


def test_v1129_top_level_mro_position_is_preserved_via_nested_bridge():
    text = MOVIE_IDENTITY.read_text(encoding="utf-8")
    assert "from .movie_bilingual_identity_v11216 import GuangYaMovieBilingualIdentityV11216Mixin" in text
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaMovieBilingualIdentityV11216Mixin):" in text
