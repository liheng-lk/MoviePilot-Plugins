from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
STATUS = PLUGIN / "status_ui_v191.py"
STATUS_HARDENING = PLUGIN / "status_hardening_v193.py"
PLANNER_SAFETY = PLUGIN / "planner_safety_v190.py"
ENTRY = PLUGIN / "__init__.py"


pkg_name = "_guangya_status_ui_testpkg"
pkg = types.ModuleType(pkg_name)
pkg.__path__ = [str(PLUGIN)]
sys.modules.setdefault(pkg_name, pkg)
spec = importlib.util.spec_from_file_location(f"{pkg_name}.status_ui_v191", STATUS)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)
GuangYaStatusUiMixin = module.GuangYaStatusUiMixin


class FakeStatus(GuangYaStatusUiMixin):
    plugin_version = "1.9.1"
    build_id = "20260901-r3"

    def __init__(self):
        self._selected_subscriptions = [1, 2]
        self._subs = {
            1: SimpleNamespace(id=1, name="示例剧 A"),
            2: SimpleNamespace(id=2, name="示例剧 B"),
        }
        self._sources = {
            "m1": {
                "id": "m1",
                "subscribe_id": 1,
                "type": "magnet",
                "state": "waiting",
                "progress": 45,
                "target_episodes": [5, 6],
                "uri": "magnet:?xt=urn:btih:abc&tr=private-tracker.example",
                "updated_at": "2026-09-01 10:00:00",
            },
            "e1": {
                "id": "e1",
                "subscribe_id": 2,
                "type": "ed2k",
                "state": "needs_review",
                "last_error": "文件集号无法可靠识别",
                "uri": "ed2k://|file|Demo.mkv|1|0123456789abcdef0123456789abcdef|/",
                "updated_at": "2026-09-01 09:59:00",
            },
        }

    def _source_store(self):
        return {"items": self._sources}

    def _find_subscription(self, sid):
        return self._subs.get(int(sid or 0))

    def _build_selfcheck(self):
        return {
            "healthy": True,
            "selected": 2,
            "checks": [
                {"key": "guangya_runtime", "label": "光鸭登录/运行时", "ok": True, "critical": True},
                {"key": "search_guard", "label": "原生搜索硬分流", "ok": True, "critical": True},
                {"key": "match_guard", "label": "RSS/缓存匹配门禁", "ok": True, "critical": True},
                {"key": "download_guard", "label": "最终下载断路器", "ok": True, "critical": True},
                {"key": "native_offline", "label": "光鸭原生云添加", "ok": True, "critical": True},
            ],
        }

    def api_resource_plan(self):
        return {
            "success": True,
            "data": [{"subscribe_id": 2, "name": "示例剧 B", "uncovered": [4, 5], "updated_at": "2026-09-01 10:00:00"}],
        }

    def get_data(self, key):
        if key == "channel_index":
            return {"time": "2026-09-01 10:01:00", "items": [{"id": 1}, {"id": 2}, {"id": 3}], "errors": []}
        if key == "last_run":
            return {"time": "2026-09-01 10:01:00"}
        if key == "transfer_jobs":
            return {
                "j1": {"subscribe_id": 1, "status": "verifying", "updated_at": "2026-09-01 10:00:30"},
                "j2": {"subscribe_id": 2, "status": "failed", "error": "目标目录确认失败", "updated_at": "2026-09-01 09:58:00"},
            }
        return {}


def _page_text(page):
    return json.dumps(page, ensure_ascii=False)


def test_status_ui_is_single_compact_five_section_page():
    pages = FakeStatus().get_page()
    assert len(pages) == 5
    assert [page.get("component") for page in pages] == ["VCard"] * 5
    text = _page_text(pages)
    for title in ("光鸭转存助手", "当前状态", "需要处理", "正在处理", "系统状态"):
        assert title in text
    for legacy_title in (
        "高级诊断",
        "为什么还没转存",
        "Magnet / ED2K 云添加任务",
        "资源组决策 · 缺集拆包",
        "有资源需要人工确认",
        "固定分流路由健康",
    ):
        assert legacy_title not in text


def test_status_ui_only_surfaces_real_attention_and_active_work():
    pages = FakeStatus().get_page()
    text = _page_text(pages)
    assert "ED2K · 示例剧 B" in text
    assert "文件集号无法可靠识别" in text
    assert "目标目录确认失败" in text
    assert "MAGNET · 示例剧 A" in text
    assert "45%" in text
    assert "E05, E06" in text
    assert "光鸭转存 · 示例剧 A" in text
    assert "资源暂未覆盖" not in text
    assert "E04, E05" not in text
    assert "等待资源" in text
    assert "正常等待，不算异常" in text


def test_status_overview_counts_waiting_separately_from_attention():
    overview = FakeStatus().api_status_overview()["data"]
    assert overview["waiting_resource_count"] == 1
    assert overview["attention_count"] == 2
    assert len(overview["active_transfer_rows"]) == 1
    assert len(overview["active_sources"]) == 1


def test_status_ui_never_leaks_raw_source_uri_or_tracker():
    text = _page_text(FakeStatus().get_page())
    assert "private-tracker.example" not in text
    assert "magnet:?" not in text
    assert "ed2k://" not in text


def test_status_ui_primary_actions_are_only_three_clear_operations():
    pages = FakeStatus().get_page()
    hero = pages[0]
    text = _page_text(hero)
    assert text.count('"component": "VBtn"') == 3
    assert "刷新频道" in text
    assert "刷新云任务" in text
    assert "运行自检" in text
    assert "GuangYaTransferAssistant/refresh" in text
    assert "GuangYaTransferAssistant/offline/refresh" in text
    assert "GuangYaTransferAssistant/selfcheck" in text


def test_status_ui_exposes_overview_api_and_r7_keeps_single_display_owner():
    status = STATUS.read_text(encoding="utf-8")
    hardening = STATUS_HARDENING.read_text(encoding="utf-8")
    safety = PLANNER_SAFETY.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    assert '"/status/overview"' in status
    assert "class GuangYaPlannerSafetyMixin(GuangYaStatusUiMixin)" in safety
    assert "return GuangYaStatusUiMixin.get_page(self)" in safety
    assert "GuangYaStatusHardeningMixin" in hardening
    start = entry.index("class GuangYaTransferAssistant")
    assert entry.index("GuangYaStatusHardeningMixin,", start) < entry.index("GuangYaPlannerSafetyMixin,", start)
    assert "资源策略：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K" in hardening
    assert "viewing_session_state" in hardening
    assert "xunlei_flash_state" in hardening


def test_status_ui_v191_is_retained_by_current_release():
    entry = ENTRY.read_text(encoding="utf-8")
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.10.7"
    assert 'plugin_version = "1.10.7"' in entry
    assert 'build_id = "20260902-r18"' in entry
    assert "v1.9.1" in package.get("history", {})
    assert "紧凑" in package["history"]["v1.9.1"]
