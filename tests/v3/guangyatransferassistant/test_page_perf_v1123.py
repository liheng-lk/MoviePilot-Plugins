from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = (PLUGIN / "page_perf_v1123.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v1123_page_layer_parses_and_is_outermost():
    ast.parse(PATCH)
    ast.parse(ENTRY)
    assert "from .page_perf_v1123 import GuangYaPagePerfV1123Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant(")
    assert ENTRY.index("GuangYaPagePerfV1123Mixin,", start) < ENTRY.index("GuangYaAiringWeeklyV1121Mixin,", start)
    assert 'build_id = "20260904-r49-preview"' in PATCH


def test_data_page_reads_snapshot_first_and_moves_media_library_sync_to_background():
    method = PATCH[PATCH.index("def _weekly_calendar_snapshot_v1121"):PATCH.index("# ------------------------------------------------------------------\n    # 数据页：真正可交互的日期 Tabs")]
    assert 'self.get_data("airing_week_view_v1121")' in method
    assert "_weekly_snapshot_usable_v1123" in method
    assert "_weekly_snapshot_stale_v1123" in method
    assert "_spawn_weekly_snapshot_refresh_v1123" in method
    assert "_sync_media_library_progress" not in method

    worker = PATCH[PATCH.index("def _spawn_weekly_snapshot_refresh_v1123"):PATCH.index("def _empty_week_snapshot_v1123")]
    assert "threading.Thread" in worker
    assert 'name="GuangYa-WeeklyPageRefresh"' in worker
    assert "super(GuangYaPagePerfV1123Mixin, self)._weekly_calendar_snapshot_v1121()" in worker
    assert "_weekly_page_refreshing_v1123" in worker


def test_interactive_weekday_page_uses_real_vuetify_tabs_and_window():
    page = PATCH[PATCH.index("def _weekly_page_v1121"):]
    assert '"component": "VTabs"' in page
    assert '"component": "VTab"' in page
    assert '"component": "VWindow"' in page
    assert '"component": "VWindowItem"' in page
    assert '"model": "_airing_day_tab"' in page
    assert '"show-arrows": True' in page
    assert '"touch": True' in page
    assert "ordered_days = days[today_index:] + days[:today_index]" in page
    assert "点击日期查看当天剧集" in page
    assert "移动端也可左右滑动日期内容" in page


def test_every_date_has_its_own_episode_cards_and_three_state_summary():
    page = PATCH[PATCH.index("def _weekly_page_v1121"):]
    assert "self._weekly_day_cards_v1123(day)" in page
    assert "已入库" in page
    assert "转存中" in page
    assert "待补" in page
    assert "day.get('library')" in page
    assert "day.get('inflight')" in page
    assert "day.get('pending')" in page


def test_large_subscription_picker_does_not_compute_episode_progress_per_option():
    options = PATCH[PATCH.index("def _subscription_options"):PATCH.index("def get_form")]
    assert "_list_subscriptions(None)" in options
    assert "state not in {\"N\", \"R\"} and sid not in selected" in options
    assert "_subscription_episode_progress" not in options
    assert 'prefix = "✓ " if picked else ""' in options


def test_large_subscription_picker_is_single_line_search_not_chip_wall():
    form = PATCH[PATCH.index("def get_form"):PATCH.index("# ------------------------------------------------------------------\n    # 数据页：快照秒开")]
    assert '"chips": False' in form
    assert '"closable-chips": False' in form
    assert '"hide-selected": False' in form
    assert '"menu-props": {"maxHeight": 420}' in form
    assert '"no-data-text": "没有匹配的活跃订阅"' in form
    assert "输入剧名 / 年份 / 季 / 订阅 ID 搜索" in form
    assert "已选项带 ✓ 并可再次点击取消" in form
    assert "页面不再铺满 chips" in form
