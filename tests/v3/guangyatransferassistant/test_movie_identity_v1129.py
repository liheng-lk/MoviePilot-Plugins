from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "movie_identity_v1129.py"
IDENTITY = PLUGIN / "media_identity_v1111.py"
ENTRY = PLUGIN / "__init__.py"


def _mixin_class(fake_media_chain):
    tree = ast.parse(PATCH.read_text(encoding="utf-8"), filename=str(PATCH))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaMovieIdentityV1129Mixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)

    class _MediaType:
        MOVIE = "movie"

    class _MediaSource:
        TMDB = "tmdb"

    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "Iterable": Iterable,
        "List": List,
        "threading": __import__("threading"),
        "time": __import__("time"),
        "MediaChain": fake_media_chain,
        "MediaType": _MediaType,
        "MediaSource": _MediaSource,
    }
    exec(compile(module, str(PATCH), "exec"), ns)
    return ns["GuangYaMovieIdentityV1129Mixin"]


class _Base:
    def init_plugin(self, config=None):
        return None

    def _identity_aliases_v1111(self, subscribe):
        return [str(getattr(subscribe, "name", "") or "")]

    def _identity_is_movie_v1111(self, subscribe):
        return str(getattr(subscribe, "type", "") or "") == "电影"


class _FakeChainFactory:
    calls = 0
    response = None

    def __new__(cls):
        return cls

    @classmethod
    def recognize_media(cls, **kwargs):
        cls.calls += 1
        cls.last_kwargs = dict(kwargs)
        return cls.response


def _movie(**overrides):
    values = {
        "id": 501,
        "name": "失控陪审团",
        "year": 2003,
        "type": "电影",
        "media_source": SimpleNamespace(value="tmdb"),
        "media_id": "11329",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _probe(response):
    _FakeChainFactory.calls = 0
    _FakeChainFactory.response = response
    _FakeChainFactory.last_kwargs = {}
    Mixin = _mixin_class(_FakeChainFactory)

    class Probe(Mixin, _Base):
        def __init__(self):
            self.logs = []
            self._movie_alias_lock_v1129 = __import__("threading").RLock()
            self._movie_alias_cache_v1129 = {}

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message % args if args else message))

    return Probe()


def _identity_func():
    ns: Dict[str, Any] = {}
    exec(compile(IDENTITY.read_text(encoding="utf-8"), str(IDENTITY), "exec"), ns)
    return ns["assess_media_identity_v1111"]


def test_v1129_layer_parses_and_is_outer_than_tv_resource_gate():
    text = PATCH.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    ast.parse(text, filename=str(PATCH))
    assert 'plugin_version = "1.12.9"' in text
    assert 'build_id = "20260905-r55"' in text
    assert "from .movie_identity_v1129 import GuangYaMovieIdentityV1129Mixin" in entry
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaMovieIdentityV1129Mixin") < head.index("GuangYaResourceGateV1127Mixin")


def test_runaway_jury_exact_tmdb_alias_rescues_real_english_resource():
    response = SimpleNamespace(
        tmdb_id=11329,
        title="失控陪审团",
        en_title="Runaway Jury",
        original_title="Runaway Jury",
        year=2003,
    )
    probe = _probe(response)
    subscribe = _movie()
    aliases = probe._identity_aliases_v1111(subscribe)

    assert "失控陪审团" in aliases
    assert "Runaway Jury" in aliases
    assert _FakeChainFactory.calls == 1
    assert _FakeChainFactory.last_kwargs["media_id"] == "11329"
    assert _FakeChainFactory.last_kwargs["mtype"] == "movie"
    assert _FakeChainFactory.last_kwargs["media_source"] == "tmdb"

    assess = _identity_func()
    old = assess(
        aliases=["失控陪审团"],
        expected_year=2003,
        expected_season=0,
        is_movie=True,
        primary_evidences=["Runaway Jury 2003"],
        file_evidences=["Runaway.Jury.2003.1080p.BluRay.mkv"],
        discovery_evidences=["失控陪审团"],
        threshold=50,
    )
    assert old["ok"] is False
    assert old["hard_conflict"] is True

    fixed = assess(
        aliases=aliases,
        expected_year=2003,
        expected_season=0,
        is_movie=True,
        primary_evidences=["Runaway Jury 2003"],
        file_evidences=["Runaway.Jury.2003.1080p.BluRay.mkv"],
        discovery_evidences=["失控陪审团"],
        threshold=50,
    )
    assert fixed["ok"] is True
    assert fixed["primary_match"] is True


def test_wrong_tmdb_identity_never_contributes_aliases():
    probe = _probe(SimpleNamespace(
        tmdb_id=99999,
        title="失控陪审团",
        en_title="Runaway Jury",
        original_title="Runaway Jury",
        year=2003,
    ))
    aliases = probe._identity_aliases_v1111(_movie())
    assert aliases == ["失控陪审团"]
    assert any("TMDB返回身份不一致" in message for _, message in probe.logs)


def test_wrong_tmdb_year_never_contributes_aliases():
    probe = _probe(SimpleNamespace(
        tmdb_id=11329,
        title="失控陪审团",
        en_title="Runaway Jury",
        original_title="Runaway Jury",
        year=2004,
    ))
    aliases = probe._identity_aliases_v1111(_movie())
    assert aliases == ["失控陪审团"]
    assert any("TMDB返回年份不一致" in message for _, message in probe.logs)


def test_non_movie_does_not_call_tmdb_alias_enrichment():
    probe = _probe(SimpleNamespace(tmdb_id=11329, en_title="Runaway Jury", year=2003))
    subscribe = _movie(type="电视剧")
    aliases = probe._identity_aliases_v1111(subscribe)
    assert aliases == ["失控陪审团"]
    assert _FakeChainFactory.calls == 0


def test_movie_alias_lookup_is_cached_for_same_tmdb_identity():
    probe = _probe(SimpleNamespace(
        tmdb_id=11329,
        title="失控陪审团",
        en_title="Runaway Jury",
        original_title="Runaway Jury",
        year=2003,
    ))
    subscribe = _movie()
    first = probe._identity_aliases_v1111(subscribe)
    second = probe._identity_aliases_v1111(subscribe)
    assert first == second
    assert "Runaway Jury" in first
    assert _FakeChainFactory.calls == 1
