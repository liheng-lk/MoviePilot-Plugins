"""光鸭转存助手 2.0：迁移 / 匹配 / 命名 / WriteGate / UI schema 合同测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "plugins.v3" / "guangyatransferassistant"


def _ensure_pkg(name: str, path: Path) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


def _load(name: str, file_path: Path):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(file_path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, file_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _import_v2():
    _ensure_pkg("plugins", ROOT / "plugins")
    _ensure_pkg("plugins.v3", ROOT / "plugins.v3")
    base = "plugins.v3.guangyatransferassistant"
    _ensure_pkg(base, PKG)

    config = _load(f"{base}.gy2_config", PKG / "gy2_config.py")
    media = _load(f"{base}.gy2_media", PKG / "gy2_media.py")
    naming = _load(f"{base}.gy2_naming", PKG / "gy2_naming.py")
    match = _load(f"{base}.gy2_match", PKG / "gy2_match.py")
    plan = _load(f"{base}.gy2_plan", PKG / "gy2_plan.py")
    migrate = _load(f"{base}.gy2_migrate", PKG / "gy2_migrate.py")
    trace = _load(f"{base}.gy2_trace", PKG / "gy2_trace.py")
    schema = _load(f"{base}.gy2_ui", PKG / "gy2_ui.py")
    return SimpleNamespace(
        CONFIG_DEFAULTS_V2=config.CONFIG_DEFAULTS_V2,
        merge_config_defaults=config.merge_config_defaults,
        MatchEngine=match.MatchEngine,
        TITLE_NOISE=match.TITLE_NOISE,
        ACCEPT=match.ACCEPT,
        MediaIdentity=media.MediaIdentity,
        NamingPolicy=naming.NamingPolicy,
        WriteGate=plan.WriteGate,
        order_candidates=plan.order_candidates,
        SOURCE_PRIORITY=plan.SOURCE_PRIORITY,
        ConfigMigratorV2=migrate.ConfigMigratorV2,
        TARGET_SCHEMA=migrate.TARGET_SCHEMA,
        DecisionTraceStore=trace.DecisionTraceStore,
        build_config_form=schema.build_config_form,
        build_data_page=schema.build_data_page,
    )


class _MemPlugin:
    def __init__(self):
        self._store: Dict[str, Any] = {}

    def get_data(self, key: str):
        return self._store.get(key)

    def save_data(self, key: str, value: Any):
        self._store[key] = value

    def _plugin_log(self, *args, **kwargs):
        return None


def test_indexes_and_entry_are_v2():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PKG / "plugin.json").read_text(encoding="utf-8"))
    entry = (PKG / "__init__.py").read_text(encoding="utf-8")
    assert package["version"] == local["version"] == "2.0.4"
    assert "v2.0.4" in package["history"]
    assert "v2.0.0" in package["history"]
    assert "v1.12.26" in package["history"]
    assert 'plugin_version = "2.0.4"' in entry
    assert 'build_id = "20260910-r84"' in entry
    assert "_GuangYaTransferV2Mixin" not in entry
    assert "gy2_plugin" not in entry
    assert package.get("release") is True
    assert not (PKG / "v2").exists()
    assert (PKG / "gy2_plugin.py").exists()
    assert "plugin_name =" not in (PKG / "gy2_plugin.py").read_text(encoding="utf-8")
    head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaPagePerfV1123Mixin" in head
    assert "_GuangYaTransferV2Mixin" not in head


def test_merge_config_preserves_user_values():
    v2 = _import_v2()
    merged = v2.merge_config_defaults({"enabled": True, "channel_urls": "https://tgm.example/a"})
    assert merged["enabled"] is True
    assert merged["channel_urls"] == "https://tgm.example/a"
    assert "ui_v2" in merged
    for key in v2.CONFIG_DEFAULTS_V2:
        assert key in merged


def test_migrator_fills_state_once():
    v2 = _import_v2()
    plugin = _MemPlugin()
    report = v2.ConfigMigratorV2(plugin).migrate()
    assert report["from_schema"] == 0
    assert report["to_schema"] == v2.TARGET_SCHEMA
    assert "decision_traces" in report["touched_state"]
    assert plugin.get_data("plugin_schema_v2")["schema"] == 2
    again = v2.ConfigMigratorV2(plugin).migrate()
    assert again.get("skipped") is True


def test_match_engine_title_noise_and_accept():
    v2 = _import_v2()
    engine = v2.MatchEngine()
    identity = v2.MediaIdentity(
        subscribe_id=1,
        name="花开锦绣",
        year=2026,
        season=1,
        media_source="tmdb",
        media_id="287496",
        is_movie=False,
    )
    good = {
        "display_title": "名称：花开锦绣 (2026) 4K 更新至12集",
        "tmdb_id": "287496",
        "share_url": "https://www.guangyapan.com/s/abc",
        "text": "名称：花开锦绣 (2026)\nTMDB: 287496",
    }
    ok = engine.match_entry(good, identity)
    assert ok.accepted and ok.reason_code == v2.ACCEPT

    noise = {
        "display_title": "[剧集·光鸭] 完全不同的剧",
        "share_url": "https://www.guangyapan.com/s/zzz",
        "text": "完全不同的剧",
    }
    bad = engine.match_entry(noise, identity)
    assert not bad.accepted and bad.reason_code == v2.TITLE_NOISE


def test_naming_policy_tv_and_movie():
    v2 = _import_v2()
    namer = v2.NamingPolicy()
    sub = SimpleNamespace(name="花开锦绣 (2026)", season=1)
    assert namer.canonical_name(sub, "whatever.S01E07.mkv", is_movie=False) == "花开锦绣 S01E07.mkv"
    assert namer.canonical_name(sub, "pack.E03-E05.mkv", is_movie=False) == "花开锦绣 S01E03-E05.mkv"
    movie = SimpleNamespace(name="荣光与暗影", season=None)
    assert namer.canonical_name(movie, "x.mkv", is_movie=True) == "荣光与暗影.mkv"


def test_write_gate_fail_closed_and_priority():
    v2 = _import_v2()
    gate = v2.WriteGate()
    closed = gate.decide(
        library_missing=None,
        logical_missing=[1, 2],
        library_unavailable=True,
    )
    assert not closed.allowed and closed.reason_code == "LIBRARY_UNAVAILABLE"

    ok = gate.decide(
        library_missing=[2, 3, 4],
        logical_missing=[1, 2, 3],
        reserved=[2],
        claimed=[],
        physical_episodes=[3],
    )
    assert ok.allowed and ok.allowed_episodes == {3}

    assert v2.order_candidates(["ed2k", "xunlei_flash", "share", "magnet"]) == [
        "xunlei", "guangya", "magnet", "ed2k"
    ]
    assert list(v2.SOURCE_PRIORITY) == ["xunlei", "guangya", "magnet", "ed2k"]


def test_trace_store_and_ui_schema():
    v2 = _import_v2()
    plugin = _MemPlugin()
    store = v2.DecisionTraceStore(plugin)
    store.append(
        subscribe_id=9,
        title="花开锦绣",
        stage="match",
        decision="reject",
        reason_code="TITLE_NOISE",
        message="标题未匹配",
    )
    rejects = store.rejected_hits(limit=10)
    assert len(rejects) == 1 and rejects[0]["reason_code"] == "TITLE_NOISE"

    form, defaults = v2.build_config_form({"enabled": False})
    blob = json.dumps(form, ensure_ascii=False)
    assert "光鸭转存助手 2.0" in blob
    assert "selected_subscriptions" in blob
    assert "channel_urls" in blob
    assert defaults["ui_v2"] is True

    page = v2.build_data_page(
        overview={"healthy": True, "selected": 1, "attention_count": 1, "summary": "ok"},
        subscription_rows=[{"id": 1, "name": "花开锦绣", "missing": "7", "inflight": "-", "block_reason": ""}],
        reject_rows=rejects,
        trace_rows=store.recent(limit=5),
    )
    page_blob = json.dumps(page, ensure_ascii=False)
    assert "命中未转" in page_blob
    assert "TITLE_NOISE" in page_blob
    assert "立即处理缺失" in page_blob
