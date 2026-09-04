from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = (PLUGIN / "page_perf_v1123.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")


def test_v1124_page_layer_parses_and_is_outermost():
    ast.parse(PATCH)
    ast.parse(ENTRY)
    assert "from .page_perf_v1123 import GuangYaPagePerfV1123Mixin" in ENTRY
    start = ENTRY.index("class GuangYaTransferAssistant(")
    assert ENTRY.index("GuangYaPagePerfV1123Mixin,", start) < ENTRY.index("GuangYaAiringWeeklyV1121Mixin,", start)
    assert 'build_id = "20260904-r50-preview"' in PATCH
    # 预览修复分支不提前发布市场版本；正式发布时再统一升版本号和入口 build。
    assert 'plugin_version = "1.12.3"' in ENTRY
    assert 'build_id = "20260904-r49"' in ENTRY


def test_data_page_reads_snapshot_first_and_moves_media_library_sync_to_background():
    method = PATCH[PATCH.index("def _weekly_calendar_snapshot_v1121"):PATCH.index("# ------------------------------------------------------------------\n    # 数据页：PageRender 原生即时日期切换")]
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


def test_date_switch_uses_native_details_not_unbound_vtabs_window_model():
    page = PATCH[PATCH.index("def _weekly_page_v1121"):]
    assert '"component": "details"' in page
    assert '"component": "summary"' in page
    assert '"name": "guangya-airing-day"' in page
    assert '"open": is_today' in page
    assert "ordered_days = days[today_index:] + days[:today_index]" in page
    assert "PageRender 只会 v-bind props" in page
    assert "点击任意日期立即展开对应剧集" in page
    assert "不发接口请求、不等待后台" in page
    for forbidden in ('"component": "VTabs"', '"component": "VTab"', '"component": "VWindow"', '"component": "VWindowItem"', '"model": "_airing_day_tab"'):
        assert forbidden not in page


def test_every_date_uses_lightweight_rows_and_three_state_summary():
    page = PATCH[PATCH.index("def _weekly_page_v1121"):]
    rows = PATCH[PATCH.index("def _weekly_day_rows_v1124"):PATCH.index("def _weekly_page_v1121")]
    assert "self._weekly_day_rows_v1124(day)" in page
    assert "已入库" in page
    assert "转存中" in page
    assert "待补" in page
    assert "day.get('library')" in page
    assert "day.get('inflight')" in page
    assert "day.get('pending')" in page
    assert '"component": "VCard"' in rows
    assert "S{season:02d}E{episode:02d}" in rows
    # 7 天隐藏内容不再调用海报卡，避免首次切日期才加载大批 VImg。
    assert "_episode_card_v1121" not in rows
    assert '"VImg"' not in rows


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
