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
PLANNER_SAFETY = PLUGIN / "planner_safety_v190.py"
ENTRY = PLUGIN / "__init__.py"


# 建立最小包环境，让 status_ui_v191 的相对导入可在不安装 MoviePilot 的 CI 中运行。
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

    def _list_subscriptions(self, _state):
        return list(self._subs.values())

    def _find_subscription(self, sid):
        return self._subs.get(int(sid or 0))

    def _diagnose_subscription(self, subscribe):
        if int(subscribe.id) == 1:
            return {
                "id": 1,
                "name": "示例剧 A",
                "severity": "info",
                "reason": "等待云添加",
                "done": 4,
                "total": 8,
                "lack": 4,
            }
        return {
            "id": 2,
            "name": "示例剧 B",
            "severity": "warning",
            "reason": "当前资源需要人工确认",
            "done": 2,
            "total": 6,
            "lack": 4,
        }

    def _build_selfcheck(self):
        return {
            "healthy": True,
            "selected": 2,
            "pending_jobs": 1,
            "failed_jobs": 0,
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
            "data": [
                {
                    "subscribe_id": 2,
                    "name": "示例剧 B",
                    "uncovered": [4, 5],
                    "updated_at": "2026-09-01 10:00:00",
                }
            ],
        }

    def get_data(self, key):
        if key == "channel_index":
            return {
                "time": "2026-09-01 10:01:00",
                "items": [{"id": 1}, {"id": 2}, {"id": 3}],
                "errors": [],
            }
        if key == "last_run":
            return {"time": "2026-09-01 10:01:00"}
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
    # 旧版逐层堆叠的长诊断区不应再进入最终首页。
    for legacy_title in (
        "高级诊断",
        "为什么还没转存",
        "Magnet / ED2K 云添加任务",
        "资源组决策 · 缺集拆包",
        "有资源需要人工确认",
        "固定分流路由健康",
    ):
        assert legacy_title not in text


def test_status_ui_only_surfaces_attention_and_active_not_full_history():
    pages = FakeStatus().get_page()
    text = _page_text(pages)
    assert "ED2K · 示例剧 B" in text
    assert "文件集号无法可靠识别" in text
    assert "MAGNET · 示例剧 A" in text
    assert "45%" in text
    assert "E05, E06" in text
    assert "资源暂未覆盖 · 示例剧 B" in text
    assert "E04, E05" in text


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


def test_status_ui_exposes_overview_api_and_planner_is_final_display_owner():
    status = STATUS.read_text(encoding="utf-8")
    safety = PLANNER_SAFETY.read_text(encoding="utf-8")
    assert '"/status/overview"' in status
    assert "class GuangYaPlannerSafetyMixin(GuangYaStatusUiMixin)" in safety
    assert "return GuangYaStatusUiMixin.get_page(self)" in safety
    # 旧层可以继续保留自己的诊断实现供 API/回归使用，但最终 PlannerSafety 不应再 super 拼页。
    page_method = safety.split("    def get_page(self):", 1)[1].split("\n\n\n__all__", 1)[0]
    assert "super().get_page" not in page_method


def test_status_ui_release_metadata_is_v191():
    entry = ENTRY.read_text(encoding="utf-8")
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.9.1"
    assert 'plugin_version = "1.9.1"' in entry
    assert 'build_id = "20260901-r3"' in entry
    assert "v1.9.1" in package.get("history", {})
