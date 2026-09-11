"""TMDB media_source normalization：themoviedb 必须被识别为 TMDB。"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def _load_media_source():
    name = "plugins.v3.guangyatransferassistant.media_source_v209"
    if name in sys.modules:
        return sys.modules[name]
    pkg = "plugins.v3.guangyatransferassistant"
    if pkg not in sys.modules:
        mod = types.ModuleType(pkg)
        mod.__path__ = [str(PLUGIN)]
        sys.modules[pkg] = mod
        sys.modules.setdefault("plugins", types.ModuleType("plugins"))
        sys.modules.setdefault("plugins.v3", types.ModuleType("plugins.v3"))
        sys.modules["plugins.v3"].__path__ = [str(ROOT / "plugins.v3")]
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "media_source_v209.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    mod.__package__ = pkg
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_tmdb_source_normalization():
    ms = _load_media_source()
    assert ms.is_tmdb_source("themoviedb") is True
    assert ms.is_tmdb_source("TMDB") is True
    assert ms.is_tmdb_source("tmdb") is True
    assert ms.is_tmdb_source("TheMovieDB") is True
    assert ms.normalize_media_source_token("themoviedb") == "tmdb"
    assert ms.normalize_media_source_token("TMDB") == "tmdb"
    assert ms.is_tmdb_source("imdb") is False
    assert ms.is_tmdb_source("douban") is False
    assert ms.is_tmdb_source("bangumi") is False
    assert ms.is_tmdb_source("anilist") is False
    assert ms.is_tmdb_source("") is False
    assert ms.is_tmdb_source(None) is False
    # Prove the old bug pattern is wrong and our helper avoids it.
    assert ("tmdb" in "themoviedb") is False
    assert ms.is_tmdb_source("themoviedb") is True

    class FakeEnum:
        value = "themoviedb"
        name = "TMDB"

    assert ms.is_tmdb_source(FakeEnum()) is True
    assert ms.normalize_media_source_token(FakeEnum()) == "tmdb"


def _load_core_tmdb_helpers():
    ms = _load_media_source()
    tree = ast.parse((PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaCorePipelineV11214Mixin")
    wanted = {"_tmdb_id_tv_v11214", "_flatten_aliases_v11214"}
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    stub = ast.ClassDef(
        name="GuangYaCorePipelineV11214Mixin",
        bases=[],
        keywords=[],
        body=methods or [ast.Pass()],
        decorator_list=[],
    )
    mod = ast.Module(body=[stub], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Sequence": Sequence,
        "Set": Set,
        "Tuple": Tuple,
        "Iterable": Iterable,
        "is_tmdb_source": ms.is_tmdb_source,
        "normalize_media_source_token": ms.normalize_media_source_token,
    }
    exec(compile(mod, str(PLUGIN / "core_pipeline_v11214.py"), "exec"), ns)
    return ns["GuangYaCorePipelineV11214Mixin"]


def test_tv_tmdb_id_from_themoviedb():
    Mixin = _load_core_tmdb_helpers()
    sub = SimpleNamespace(
        type="电视剧",
        media_source="themoviedb",
        media_id="324580",
        name="第一声啼哭 母子救命急救班",
        season=1,
    )
    assert Mixin._tmdb_id_tv_v11214(sub) == "324580"
    # Non-TMDB sources must stay empty
    sub.media_source = "douban"
    assert Mixin._tmdb_id_tv_v11214(sub) == ""


def _load_movie_tmdb_helper():
    ms = _load_media_source()
    tree = ast.parse((PLUGIN / "movie_identity_v1129.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaMovieIdentityV1129Mixin")
    methods = [
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"_movie_tmdb_id_v1129", "_is_movie_v1129", "_enum_token_v1129"}
    ]
    stub = ast.ClassDef(name="GuangYaMovieIdentityV1129Mixin", bases=[], keywords=[], body=methods, decorator_list=[])
    mod = ast.Module(body=[stub], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Iterable": Iterable,
        "is_tmdb_source": ms.is_tmdb_source,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "MediaChain": object,
        "MediaSource": object,
        "MediaType": object,
    }
    exec(compile(mod, str(PLUGIN / "movie_identity_v1129.py"), "exec"), ns)
    return ns["GuangYaMovieIdentityV1129Mixin"]


def test_movie_tmdb_id_from_themoviedb():
    Mixin = _load_movie_tmdb_helper()

    class Obj(Mixin):
        pass

    obj = Obj()
    sub = SimpleNamespace(type="电影", media_source="themoviedb", media_id="1285366", name="demo")
    assert obj._movie_tmdb_id_v1129(sub) == "1285366"
    sub.media_source = "imdb"
    sub.media_id = "tt123"
    assert obj._movie_tmdb_id_v1129(sub) == ""


def _load_search_recall_identity():
    ms = _load_media_source()
    tree = ast.parse((PLUGIN / "search_recall_v11217.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaSearchRecallV11217Mixin")
    wanted = {"_source_token_v11217", "_canonical_identity_v11217", "_row_explicit_identity_v11217"}
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in wanted]
    stub = ast.ClassDef(name="GuangYaSearchRecallV11217Mixin", bases=[], keywords=[], body=methods, decorator_list=[])
    mod = ast.Module(body=[stub], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Sequence": Sequence,
        "Set": Set,
        "Tuple": Tuple,
        "Iterable": Iterable,
        "is_tmdb_source": ms.is_tmdb_source,
        "is_imdb_source": ms.is_imdb_source,
        "normalize_media_source_token": ms.normalize_media_source_token,
    }
    exec(compile(mod, str(PLUGIN / "search_recall_v11217.py"), "exec"), ns)
    return ns["GuangYaSearchRecallV11217Mixin"]


def test_search_recall_themoviedb_identity():
    Mixin = _load_search_recall_identity()
    obj = Mixin()
    sub = SimpleNamespace(media_source="themoviedb", media_id="324580", tmdb_id="", tmdbid="", imdb_id="")
    assert obj._canonical_identity_v11217(sub) == ("tmdb", "324580")
    row = {"media_source": "themoviedb", "media_id": "296436"}
    assert Mixin._row_explicit_identity_v11217(row) == ("tmdb", "296436")


def _bind_plan_with_real_tmdb_id():
    """Bind production identity gate using REAL _tmdb_id_tv_v11214 (themoviedb aware)."""
    import runpy
    r92 = SimpleNamespace(**runpy.run_path(str(Path(__file__).with_name("test_r92_identity_recall_v208.py"))))

    Core = _load_core_tmdb_helpers()
    helper = r92._bind_plan_incremental(aliases=["第一声啼哭 母子救命急救班"], tmdb_id="")
    # Replace stub with production method
    helper._tmdb_id_tv_v11214 = lambda subscribe: Core._tmdb_id_tv_v11214(subscribe)
    return helper, r92


def test_direct_share_same_tmdb_confirmed():
    helper, r92 = _bind_plan_with_real_tmdb_id()
    cases = [
        ("第一声啼哭 母子救命急救班", "324580", "第一声啼哭 母子救命急救班 (2026) {tmdb-324580}", "First.Cry/E01.mkv"),
        ("无自觉圣女今天也无意识地释放力量", "296436", "无自觉圣女今天也无意识地释放力量 (2026) {tmdb-296436}", "The.Oblivious.Saint.Can't.Contain.Her.Power/E01.mkv"),
        ("雷霆三人行", "326119", "雷霆三人行 (2026) {tmdb-326119}", "Thunder.3/E01.mkv"),
        ("盗墓王", "297826", "盗墓王 (2026) {tmdb-297826}", "Tomb.Raider.King/E01.mkv"),
    ]
    for name, tmdb, root, file_name in cases:
        helper._identity_aliases_v1111 = lambda subscribe, n=name: [n]
        probe = r92._probe_files(root, [file_name])
        stats: Dict[str, Any] = {}
        subscribe = SimpleNamespace(
            id=90,
            name=name,
            year="2026",
            season=1,
            type="电视剧",
            media_source="themoviedb",
            media_id=tmdb,
            tmdb_id="",
            tmdbid="",
        )
        assert helper._tmdb_id_tv_v11214(subscribe) == tmdb
        planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
        assert stats.get("identity_reject_v11214") != 1, (name, stats)
        assert planned, name


def test_direct_share_tmdb_mismatch_rejected():
    helper, r92 = _bind_plan_with_real_tmdb_id()
    probe = r92._probe_files(
        "第一声啼哭 母子救命急救班 (2026) {tmdb-999999}",
        ["First.Cry/E01.mkv"],
    )
    stats: Dict[str, Any] = {}
    subscribe = SimpleNamespace(
        id=90,
        name="第一声啼哭 母子救命急救班",
        year="2026",
        season=1,
        type="电视剧",
        media_source="themoviedb",
        media_id="324580",
        tmdb_id="",
        tmdbid="",
    )
    planned = helper._plan_incremental_files(probe, {}, subscribe=subscribe, target_path="/tv", stats=stats)
    assert planned == []
    assert stats.get("identity_reject_v11214") == 1
    assert "tmdb_mismatch" in str(stats.get("identity_reason") or "")


def test_official_alias_available_for_themoviedb():
    Core = _load_core_tmdb_helpers()
    sub = SimpleNamespace(
        type="电视剧",
        media_source="themoviedb",
        media_id="76662",
        name="一念永恒",
        season=1,
        tmdb_id="",
        tmdbid="",
    )
    assert Core._tmdb_id_tv_v11214(sub) == "76662"
    # Alias getter depends on MediaChain; verify ID path is unblocked so aliases can run.
    src = (PLUGIN / "core_pipeline_v11214.py").read_text(encoding="utf-8")
    assert "is_tmdb_source" in src
    assert '_tmdb_id_tv_v11214(subscribe)' in src
    assert "source_normalized" in src


def test_recognize_cache_normalizes_themoviedb_to_tmdb():
    ms = _load_media_source()
    tree = ast.parse((PLUGIN / "production_safety_v208.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuangYaProductionSafetyV208Mixin")
    methods = [
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"_enum_token_v208", "_normalize_mtype_v208", "_recognize_cache_key_v208"}
    ]
    stub = ast.ClassDef(name="GuangYaProductionSafetyV208Mixin", bases=[], keywords=[], body=methods, decorator_list=[])
    mod = ast.Module(body=[stub], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Iterable": Iterable,
        "is_tmdb_source": ms.is_tmdb_source,
        "normalize_media_source_token": ms.normalize_media_source_token,
        "copy": __import__("copy"),
        "threading": __import__("threading"),
        "time": __import__("time"),
        "MediaChain": object,
    }
    exec(compile(mod, str(PLUGIN / "production_safety_v208.py"), "exec"), ns)
    Mixin = ns["GuangYaProductionSafetyV208Mixin"]
    key_a = Mixin._recognize_cache_key_v208(media_source="themoviedb", media_id="324580", mtype="tv")
    key_b = Mixin._recognize_cache_key_v208(media_source="tmdb", media_id="324580", mtype="tv")
    key_c = Mixin._recognize_cache_key_v208(media_source="TMDB", media_id="324580", mtype="tv")
    assert key_a == key_b == key_c
    assert key_a.startswith("id:tmdb:tv:324580")


def test_no_bare_tmdb_in_source_in_production_identity_sites():
    files = [
        "core_pipeline_v11214.py",
        "movie_identity_v1129.py",
        "search_recall_v11217.py",
        "production_safety_v208.py",
        "legacy.py",
        "release_v1110.py",
    ]
    for name in files:
        text = (PLUGIN / name).read_text(encoding="utf-8")
        assert '"tmdb" in source' not in text, name
        assert '"tmdb" not in source' not in text, name
        assert '"tmdb" in media_source' not in text, name
        assert "is_tmdb_source" in text or name == "legacy.py"
    assert "is_tmdb_source" in (PLUGIN / "legacy.py").read_text(encoding="utf-8")
