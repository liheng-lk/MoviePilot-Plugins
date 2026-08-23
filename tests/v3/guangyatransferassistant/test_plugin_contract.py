import ast
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
text = SRC.read_text(encoding="utf-8")
tree = ast.parse(text)

# 执行 class 之前的常量与纯函数，不依赖 MoviePilot 运行时。
nodes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        break
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.FunctionDef)):
        if isinstance(node, ast.FunctionDef):
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
        nodes.append(node)
mod = ast.Module(body=nodes, type_ignores=[])
ast.fix_missing_locations(mod)
ns = {
    "ast": ast, "hashlib": hashlib, "html": html, "re": re,
    "parse_qs": parse_qs, "urlencode": urlencode, "unquote": unquote,
    "urljoin": urljoin, "urlsplit": urlsplit, "urlunsplit": urlunsplit,
    "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List,
    "Optional": Optional, "Tuple": Tuple,
}
exec(compile(mod, str(SRC), "exec"), ns)


def test_hidden_visible_and_wrapped_links():
    hidden = '''<div class="tgme_widget_message_wrap" data-post="regengguangya/100">
    <div>名称：花开锦绣 (2026) [2160P]<br>集数：第23-25集 / 全36集<br>TMDB：287496</div>
    <a class="tgme_widget_message_inline_button" href="https://www.guangyapan.com/s/hiddenABC">🔗 光鸭云盘：查看资源</a>
    </div>'''
    items = ns["_extract_channel_entries"](hidden, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1
    assert items[0]["share_id"] == "hiddenABC"
    assert items[0]["tmdb_id"] == "287496"
    assert "23-25" in items[0]["episode_hint"]
    assert "按钮" in items[0]["link_style"]

    data_url = '''<div data-post="regengguangya/1001">名称：属性按钮测试 (2026)
    <button data-url="https://www.guangyapan.com/s/dataURL123">光鸭云盘：查看资源</button></div>'''
    items = ns["_extract_channel_entries"](data_url, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1 and items[0]["share_id"] == "dataURL123"
    assert items[0]["link_style"] in ("隐藏按钮", "链接属性")

    visible = '''<div data-post="yunpanguangya/101">名称：杀手妈咪 유부녀 킬러 (2026) [1080P] [更至8集]
    链接：www.guangyapan.com/s/plainXYZ</div>'''
    items = ns["_extract_channel_entries"](visible, "https://tgm.li668.asia/yunpanguangya", "资源分享")
    assert len(items) == 1 and items[0]["share_id"] == "plainXYZ"
    assert items[0]["link_style"] == "明文链接"

    wrapped = '''<div data-post="regengguangya/102">名称：包装测试 (2026)
    <a href="/redirect?url=https%3A%2F%2Fwww.guangyapan.com%2Fs%2Fwrap123%3Fcode%3DAb12">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](wrapped, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 1 and items[0]["share_id"] == "wrap123"
    assert "code=Ab12" in items[0]["share_url"]
    assert "按钮" in items[0]["link_style"] or "包装" in items[0]["link_style"]


def test_message_boundary_and_tmdb_exact_match():
    page = '''<div data-post="regengguangya/201">名称：花开锦绣 (2026)<br>TMDB: 287496
    <a href="https://www.guangyapan.com/s/a201">查看资源</a></div>
    <div data-post="regengguangya/202">名称：完全不同 (2025)<br>TMDB: 999999
    <a href="https://www.guangyapan.com/s/a202">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](page, "https://tgm.li668.asia/regengguangya", "影视热更")
    first = next(item for item in items if item["share_id"] == "a201")
    assert "999999" not in first["text"]
    assert ns["_entry_matches_subscription"](first, "标题甚至不同也可由ID确认", 2026, 1, "themoviedb", "287496") is True
    assert ns["_entry_matches_subscription"](first, "花开锦绣", 2026, 1, "themoviedb", "999999") is False


def test_pagination_episode_and_path_safety():
    html_page = '''<a href="/regengguangya?before=123">Older</a>
    <a href="/other?before=1">Other</a><a href="/regengguangya">Same</a>'''
    pages = ns["_extract_pagination_urls"](html_page, "https://tgm.li668.asia/regengguangya")
    assert pages == ["https://tgm.li668.asia/regengguangya?before=123"]
    season, eps = ns["_episode_numbers"]("Show.S01E23-E25.2160p.WEB-DL.mkv")
    assert season == 1 and eps == [23, 24, 25]
    _, eps = ns["_episode_numbers"]("第8-10集.mp4")
    assert eps == [8, 9, 10]
    assert ns["_safe_relative_path"]("../../Season 1/../E01.mkv") == "Season 1/E01.mkv"


def test_version_and_safety_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.6.3" and local["version"] == "1.6.3"
    assert 'plugin_version = "1.6.3"' in text
    for token in (
        "隐藏按钮", "包装按钮", "_extract_pagination_urls", "tmdb_id", "TMDB精确",
        "strict_subscription_rules", "best_version", "filter_groups", "state not in (\"N\", \"R\")",
        "sync_subscription_progress", "SubscribeOper().update", "_episode_numbers",
        "max_files_per_run", "retry_minutes", "旧缓存", "stale", "clear_inventory",
        "【光鸭转存助手】【进度】", "【光鸭转存助手】【规则】", "【光鸭转存助手】【重试】",
    ):
        assert token in text, token
    assert "subscribe_search" in text and "new_subscribe_search" in text
    assert "SubscribeChain().search" in text
    assert "/nd.bizuserres.s/v1/restore_share" in text
    assert "transfer_inventory" in text and "legacy_fingerprint" in text
    assert "✅ 光鸭转存成功" in text and "⚠️ 光鸭转存失败" in text


def test_asset_identity_keeps_v11_compatibility_when_digest_absent():
    old_style = hashlib.sha256("season 1/e01.mkv|100".encode("utf-8")).hexdigest()
    assert ns["_asset_identity"]("Season 1/E01.mkv", 100) == old_style
    assert ns["_asset_identity"]("Season 1/E01.mkv", 100, "abc") != old_style



def test_fixed_routing_never_falls_back_for_selected_subscriptions():
    assert "_fallback_native" not in text
    assert '"fallback_native"' not in text
    dispatch = text.split("    def _dispatch_subscribe_search(", 1)[1].split("    def _subscription_static_guard(", 1)[0]
    assert dispatch.count("SubscribeChain().search") == 2
    assert "if int(sid) not in selected:" in dispatch
    assert "if subscribe_id in selected:" in dispatch
    assert "固定转存处理" in dispatch
    assert "continue" in dispatch
    assert "固定转存路线不触发原生下载" in text


def test_save_path_combobox_values_are_normalized():
    normalize = ns["_normalize_config_path"]
    assert normalize("/光鸭媒体库") == "/光鸭媒体库"
    assert normalize({"title": "/光鸭媒体库", "value": "/光鸭媒体库"}) == "/光鸭媒体库"
    assert normalize("{'title': '/光鸭媒体库', 'value': '/光鸭媒体库'}") == "/光鸭媒体库"
    assert normalize('{"title": "/光鸭媒体库", "value": "/光鸭媒体库"}') == "/光鸭媒体库"
    assert 'result.append(row if raw else row["value"])' in text


def test_subscription_selector_is_searchable_and_progress_aware():
    assert '"component": "VAutocomplete"' in text
    assert '搜索并选择仅使用光鸭转存的订阅' in text
    assert '可按剧名、年份、季、类型或订阅ID搜索' in text
    assert 'prepend-inner-icon' in text and 'mdi-magnify' in text
    assert '_subscription_episode_progress' in text
    assert '已完成 {done}/{total}' in text
    assert '剩余 {lack}' in text


def test_completed_guangya_subscription_uses_moviepilot_completion_flow():
    assert 'build_subscribe_meta' in text
    assert 'MediaChain().recognize_media' in text
    assert 'SubscribeChain().finish_subscribe_or_not' in text
    assert 'force=True' in text
    assert '_finish_subscription_if_complete' in text
    assert '_remove_selected_subscription' in text
    assert '已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除' in text
    assert '目标剧集已全部完成，订阅已移入历史' in text



def test_airing_and_missing_episode_contracts():
    serial = ns["_entry_serial_state"]
    current = serial({"text": "名称：测试剧 (2026) [更新至8集]", "episode_hint": "更新至8集"})
    assert current["ongoing"] is True and current["complete"] is False
    assert current["current_episode"] == 8 and current["explicit_total"] == 0
    known = serial({"text": "集数：第23-25集 / 全36集", "episode_hint": "第23-25集", "total_episode_hint": 36})
    assert known["current_episode"] == 25 and known["explicit_total"] == 36
    finished = serial({"text": "全12集 已完结"})
    assert finished["complete"] is True and finished["explicit_total"] == 12
    assert 'api_check_missing' in text and 'api_release_native' in text
    assert '立即检查缺集' in text and '切换普通下载' in text
    assert 'completion_guard' in text and '连载保护' in text
    assert '_sync_channel_episode_floor' in text
    assert 'protect_ongoing' in text and 'ongoing_guard_days' in text



def test_entry_process_key_only_changes_for_new_message_or_link():
    key = ns["_entry_process_key"]
    base = {
        "source_url": "https://tgm.li668.asia/regengguangya",
        "message_id": "100",
        "share_url": "https://www.guangyapan.com/s/abc123",
        "text": "名称：藏锋 更新至8集",
    }
    assert key(base) == key(dict(base))
    new_message = dict(base, message_id="101")
    new_link = dict(base, share_url="https://www.guangyapan.com/s/xyz999")
    assert key(base) != key(new_message)
    assert key(base) != key(new_link)


def test_processed_message_and_media_library_sync_contracts():
    assert 'from app.chain.download import DownloadChain' in text
    assert '_sync_media_library_progress' in text
    assert 'DownloadChain().get_no_exists_info' in text
    assert 'processed_entries' in text
    assert '_entry_process_key' in text
    flow = text.split('    def _try_transfer_subscription(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'if not force and self._entry_processed(entry, subscribe):' in flow
    assert '_mark_entry_processed(entry, "no_new_episode"' in flow
    assert '_mark_entry_processed(entry, "transferred"' in flow
    assert 'errors.append("分享内没有符合订阅范围的媒体/字幕文件")' not in flow
    assert '没有新链接/新消息' in flow
    assert '当前抓取' in text and '故障回退' in text
    cleanup = text.split('    def _cleanup_selected_ids(', 1)[1].split('    def _save_config(', 1)[0]
    assert '_clear_completion_guard(int(sid))' not in cleanup
    removal = text.split('    def _remove_selected_subscription(', 1)[1].split('    def _get_guangya_runtime(', 1)[0]
    assert '_clear_completion_guard(int(sid))' in removal



def test_same_share_in_new_message_is_kept_as_new_entry():
    page = '''<div data-post="regengguangya/300">名称：藏锋 (2026) 更新至8集
    <a href="https://www.guangyapan.com/s/reused001">查看资源</a></div>
    <div data-post="regengguangya/301">名称：藏锋 (2026) 更新至9集
    <a href="https://www.guangyapan.com/s/reused001">查看资源</a></div>'''
    items = ns["_extract_channel_entries"](page, "https://tgm.li668.asia/regengguangya", "影视热更")
    assert len(items) == 2
    assert {item["message_id"] for item in items} == {"300", "301"}
    keys = {ns["_entry_process_key"](item) for item in items}
    assert len(keys) == 2


def test_media_library_sync_runs_even_before_channel_match():
    flow = text.split('    def _try_transfer_subscription(', 1)[1].split('    def _target_path(', 1)[0]
    sync_pos = flow.index('self._sync_media_library_progress(subscribe)')
    no_match_pos = flow.index('if not matched_pairs:')
    assert sync_pos < no_match_pos
    assert '_entry_process_key(item) or _share_identity' in text
    assert '当前抓取' in text and '故障回退' in text



def test_movie_completion_uses_confirmed_video_or_media_library_and_official_flow():
    assert '_is_movie_subscription' in text
    assert '_movie_transfer_confirmed' in text
    helper = text.split('    def _movie_transfer_confirmed(', 1)[1].split('    def _finish_subscription_if_complete(', 1)[0]
    assert 'transfer_inventory' in helper
    assert '_is_video(path)' in helper
    assert 'DownloadChain().get_no_exists_info' in helper
    finish = text.split('    def _finish_subscription_if_complete(', 1)[1].split('    def _remove_selected_subscription(', 1)[0]
    assert 'is_movie = self._is_movie_subscription(subscribe)' in finish
    assert 'if not self._movie_transfer_confirmed(subscribe):' in finish
    assert 'SubscribeChain().finish_subscribe_or_not' in finish
    assert 'force=True' in finish
    flow = text.split('    def _try_transfer_subscription(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'pre_channel_state = self._channel_state_for_subscription(subscribe, entries)' in flow
    assert 'if self._finish_subscription_if_complete(subscribe, channel_state=pre_channel_state):' in flow
    assert '订阅已完成并移入历史' in flow



def test_v140_reliability_contracts():
    for token in (
        'media_facts', '_media_fact_prefix', '_semantic_fact_exists',
        'channel_cursors', 'last_message_id', 'reached_cursor',
        'transfer_jobs', 'active_runs', '_acquire_subscription_run',
        '_verify_restored_group', '【光鸭转存助手】【落盘确认】',
        'data_schema_version = 6',
    ):
        assert token in text, token
    assert 'plugin_version = "1.6.3"' in text
    assert '本轮新增' in text and '保留索引' in text and '故障回退' in text


def test_processed_entry_is_scoped_by_media_not_global_message():
    block = text.split('    def _processed_entry_key(', 1)[1].split('    def _entry_processed(', 1)[0]
    assert '_media_fact_prefix(subscribe)' in block
    assert 'hashlib.sha256' in block
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'self._entry_processed(entry, subscribe)' in flow
    assert '_mark_entry_processed(entry, "transferred"' in flow


def test_transfer_cap_does_not_mark_whole_message_processed():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'deferred_for_entry = max(0, pending_count - self._max_files_per_run)' in flow
    assert 'if deferred_for_entry <= 0:' in flow
    assert '不标记消息完成' in flow


def test_restore_requires_post_task_visibility_verification():
    restore = text.split('    def _restore_items(', 1)[1].split('    def _restore_share(', 1)[0]
    assert '_wait_task_done' in restore
    assert '_verify_restored_group' in restore
    assert 'task_confirmed' in restore and 'verified' in restore
    assert '目标文件可见性/大小已确认' in restore
    verify = text.split('    def _verify_restored_group(', 1)[1].split('    def _verify_restored_items(', 1)[0]
    assert '_iter_parent_items' in verify
    assert 'remote_size not in (None, 0, size)' in verify


def test_persistent_run_lock_wraps_all_transfer_calls():
    wrapper = text.split('    def _try_transfer_subscription(', 1)[1].split('    def _try_transfer_subscription_inner(', 1)[0]
    assert '_acquire_subscription_run' in wrapper
    assert 'finally:' in wrapper and '_release_subscription_run' in wrapper
    assert '已有同媒体转存任务执行中' in wrapper


def test_channel_refresh_uses_cursor_and_retains_index():
    refresh = text.split('    def refresh_channels(', 1)[1].split('    def _source_urls(', 1)[0]
    assert 'channel_cursors' in refresh
    assert 'last_message_id' in refresh
    assert 'max(page_ids) <= last_message_id' in refresh
    assert 'old["cached_index"] = True' in refresh
    assert 'self.save_data("channel_cursors", cursors)' in refresh



def test_restart_recovery_reads_old_job_before_planned_overwrite():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    read_pos = flow.index('pending_job = self._get_job_state(job_key)')
    planned_marker = 'job_key, "planned", subscribe_id=sid'
    planned_pos = flow.index(planned_marker)
    assert read_pos < planned_pos
    assert 'pending_job.get("status") in ("submitted", "task_confirmed", "verifying")' in flow


def test_file_cap_is_reported_as_partial_until_all_files_processed():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'partial = (bool(errors) or remaining_due_to_cap > 0 or pending_verification) and not completed_subscription' in flow
    assert 'if deferred_for_entry <= 0:' in flow
    assert '本轮完成后仍有 %s 个文件待下轮，不标记消息完成' in flow


def test_media_fact_progress_is_clipped_to_current_subscription_target():
    block = text.split('    def _sync_media_facts_progress(', 1)[1].split('    def _processed_entry_key(', 1)[0]
    assert 'episodes = episodes.intersection(target)' in block
    assert 'merged = current | episodes' in block



def test_pending_visibility_never_downgrades_to_failed_or_auto_replays():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'pending_verification = False' in flow
    assert '已提交任务不会自动重复提交' in flow
    assert 'if restored.get("pending_verification"):' in flow
    pending_branch = flow.split('if restored.get("pending_verification"):', 1)[1].split('else:', 1)[0]
    assert '_set_job_state(job_key, "verifying"' in pending_branch
    assert '_set_job_state(job_key, "failed"' not in pending_branch
    assert 'if pending_verification and not errors:' in flow
    assert '不会重复提交' in flow


def test_visibility_timeout_remains_pending_until_manual_force():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    recovery = flow.split('pending_job.get("status") in ("submitted", "task_confirmed", "verifying")', 1)[1].split('if restored is None:', 1)[0]
    assert '落盘确认已超等待窗口，保持待确认以避免重复提交' in recovery
    assert 'continue' in recovery
    assert 'force' in flow
    restore = text.split('    def _restore_items(', 1)[1].split('    def _restore_share(', 1)[0]
    assert '"pending_verification": True' in restore



def test_v150_version_and_console_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.6.3" and local["version"] == "1.6.3"
    assert 'plugin_version = "1.6.3"' in text
    assert '_subscription_console_snapshot' in text
    assert '等待落盘确认' in text and '当前已齐 · 连载保护中' in text
    assert '复查待落盘' in text and '重置检查状态' in text
    assert '/recheck_pending' in text and '/reset_state' in text
    assert '媒体事实' in text and '已处理消息' in text and '最近频道消息' in text


def test_alias_matching_never_overrides_tmdb_conflict():
    class Sub:
        name = '中文主标题'
        original_title = 'Library Sheep'
        year = 2026
        season = 1
        media_source = 'themoviedb'
        media_id = '12345'
    sub = Sub()
    alias_entry = {
        'text': '名称：Library Sheep (2026) S01',
        'display_title': 'Library Sheep (2026)',
        'tmdb_id': '',
    }
    assert ns['_entry_match_reason'](alias_entry, sub) == (True, '别名匹配')
    conflict = dict(alias_entry, tmdb_id='99999')
    assert ns['_entry_match_reason'](conflict, sub) == (False, '')
    assert 'SequenceMatcher' not in text and 'rapidfuzz' not in text


def test_extended_episode_parser_contracts():
    parser = ns['_episode_numbers']
    assert parser('Show.S01.EP.08.2160p.mkv') == (1, [8])
    assert parser('Show.1x09.WEB-DL.mkv') == (1, [9])
    assert parser('Show.S01E10E11E12.mkv') == (1, [10, 11, 12])
    assert parser('动画 第13-15话.mp4')[1] == [13, 14, 15]


def test_single_subscription_reset_is_safe():
    block = text.split('    def _reset_subscription_check_state(', 1)[1].split('    def get_page(', 1)[0]
    assert 'submitted' in block and 'task_confirmed' in block and 'verifying' in block
    assert '请先复查待落盘状态' in block
    assert 'processed_entries' in block and 'failure_notices' in block
    assert 'media_facts' not in block.replace('媒体事实/库存/进度均保留', '')
    assert 'transfer_inventory' not in block
    assert '媒体事实/库存/进度均保留' in block


def test_pending_recheck_does_not_force_replay():
    block = text.split('    def api_recheck_pending(', 1)[1].split('    def api_reset_state(', 1)[0]
    assert '_try_transfer_subscription(subscribe, force=False)' in block
    assert 'force=True' not in block


def test_failure_notice_fingerprint_ignores_dynamic_ids():
    fp = ns['_failure_notice_fingerprint']
    left = fp('share_id=AbCdEf123 task_id=ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 网络错误')
    right = fp('share_id=Other999 task_id=ZZZZZZZZZZZZZZZZZZZZZZZZZZZZ 网络错误')
    assert left == right



def test_v160_operations_and_audit_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.6.3" and local["version"] == "1.6.3"
    assert 'plugin_version = "1.6.3"' in text
    assert '_task_audit_rows' in text and '转存任务审计' in text
    assert '忽略卡住任务' in text and '/cancel_pending' in text
    assert '旧消息不会自动重放' in text
    assert 'daily_summary' in text and 'summary_cron' in text and '光鸭转存日报' in text
    assert 'CronTrigger.from_crontab' in text
    assert '_data_schema_version = 6' in text


def test_manual_missing_check_refuses_pending_force_replay():
    guard = text.split('    def _manual_transfer_guard(', 1)[1].split('    def get_api(', 1)[0]
    assert '_pending_jobs_for_subscription(subscribe)' in guard
    assert '请先使用‘复查待落盘’' in guard
    block = text.split('    def api_check_missing(', 1)[1].split('    def api_recheck_pending(', 1)[0]
    guard_pos = block.index('_manual_transfer_guard(subscribe)')
    force_pos = block.index('_try_transfer_subscription(subscribe, force=True)')
    assert guard_pos < force_pos


def test_cancelled_old_job_never_replays_until_reset():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'pending_job.get("status") == "cancelled"' in flow
    cancelled = flow.split('pending_job.get("status") == "cancelled"', 1)[1].split('self._plugin_log("INFO", ', 1)[0]
    assert 'continue' not in cancelled  # continue follows the explanatory log, not before it
    assert '该旧消息任务已人工忽略' in flow and 'continue' in flow
    reset = text.split('    def _reset_subscription_check_state(', 1)[1].split('    def _pending_jobs_for_subscription(', 1)[0]
    assert '"cancelled"' in reset


def test_special_episode_parser_and_season_zero_identity():
    parser = ns['_episode_numbers']
    assert parser('Anime.OVA.01.1080p.mkv') == (0, [1])
    assert parser('Anime.SP02.mkv') == (0, [2])
    assert parser('动画 特别篇3.mp4') == (0, [3])
    assert parser('Show.S00E04.mkv') == (0, [4])
    assert parser('Show.S01E08.SP1.mkv') == (1, [8])
    assert 'wanted_value == 0 and file_season is None' in text
    assert 'wanted_season == 0 and file_season is None' in text


def test_daily_summary_is_optional_and_deduplicated():
    service = text.split('    def get_service(', 1)[1].split('    def get_form(', 1)[0]
    assert 'if self._daily_summary:' in service
    assert 'GuangYaTransferAssistantDailySummary' in service
    summary = text.split('    def _send_daily_summary(', 1)[1].split('    def get_page(', 1)[0]
    assert 'daily_summary_state' in summary
    assert '今日摘要已发送' in summary
    assert 'force: bool = False' in text



def test_inflight_reservations_prevent_cross_message_duplicate_submission():
    assert '_pending_reservations' in text and '_filter_inflight_planned_items' in text
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    plan_pos = flow.index('_plan_incremental_files')
    reserve_pos = flow.index('_filter_inflight_planned_items')
    submit_pos = flow.index('_restore_items')
    assert plan_pos < reserve_pos < submit_pos
    assert '【光鸭转存助手】【在途去重】' in flow
    assert '可转内容全部已在其它任务中' in flow
    helper = text.split('    def _pending_reservations(', 1)[1].split('    def _cancel_pending_jobs(', 1)[0]
    assert '{"submitted", "task_confirmed", "verifying"}' in helper
    assert 'episodes.update' in helper
    assert 'movie_pending = True' in helper


def test_inflight_only_message_is_not_marked_permanently_processed():
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    block = flow.split('if not planned:', 1)[1].split('attempted_new = True', 1)[0]
    inflight = block.split('if inflight_held:', 1)[1].split('self._mark_entry_processed', 1)[0]
    assert 'continue' in inflight
    assert '_mark_entry_processed' not in inflight



def test_v161_season_zero_library_sync_and_manual_gate_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.6.3" and local["version"] == "1.6.3"
    assert 'plugin_version = "1.6.3"' in text

    sync = text.split('    def _sync_media_library_progress(', 1)[1].split('    def _install_takeover(', 1)[0]
    assert 'raw_season = getattr(subscribe, "season", None)' in sync
    assert 'is_tv =' in sync
    assert 'season = int(raw_season)' in sync
    assert 'if season < 0 or total < start:' in sync
    assert 'if season <= 0' not in sync
    assert 'totals={season: total}' in sync

    guard = text.split('    def _manual_transfer_guard(', 1)[1].split('    def get_api(', 1)[0]
    assert 'sid not in set(self._selected_subscriptions)' in guard
    assert 'state not in ("N", "R")' in guard
    assert '_pending_jobs_for_subscription(subscribe)' in guard
    assert '复查待落盘' in guard

    transfer = text.split('    def api_transfer(', 1)[1].split('    def api_folders(', 1)[0]
    assert '_manual_transfer_guard(subscribe)' in transfer
    assert transfer.index('_manual_transfer_guard(subscribe)') < transfer.index('_try_transfer_subscription(subscribe, force=True)')

    missing = text.split('    def api_check_missing(', 1)[1].split('    def api_recheck_pending(', 1)[0]
    assert '_manual_transfer_guard(subscribe)' in missing
    assert missing.index('_manual_transfer_guard(subscribe)') < missing.index('_try_transfer_subscription(subscribe, force=True)')


def test_v161_mutating_plugin_apis_use_post():
    api = text.split('    def get_api(', 1)[1].split('    def api_refresh(', 1)[0]
    assert '{"path": "/folders", "endpoint": self.api_folders, "methods": ["GET"]' in api
    for endpoint in ('check_missing', 'release_native', 'recheck_pending', 'reset_state', 'cancel_pending', 'daily_summary'):
        assert f'{{"path": "/{endpoint}"' in api
        fragment = api.split(f'{{"path": "/{endpoint}"', 1)[1].split('}', 1)[0]
        assert '"methods": ["POST"]' in fragment
    for endpoint in ('check_missing', 'release_native', 'recheck_pending', 'reset_state', 'cancel_pending'):
        assert f'"api": "plugin/GuangYaTransferAssistant/{endpoint}", "method": "post"' in text



def test_v162_emoji_channel_title_parser_keeps_full_titles():
    parser = ns['_entry_metadata']
    law = (
        '光鸭云盘影视热更频道 🎬 法律边缘 (2026) 已更新 🎭 类型： 电视剧 · 犯罪 / 剧情 '
        '⭐ TMDB评分： 5.0 🖥 画质： 2160p 📺 质量： WEB-DL DDP Atmos H.265 '
        '📼 集数： 全7集 📦 大小： 36.32GB 👤 分享： 热心网友'
    )
    meta = parser(law, '<div data-post="regengguangya/9001"></div>')
    assert meta['display_title'] == '法律边缘'
    assert meta['year_hint'] == 2026
    assert meta['total_episode_hint'] == 7
    assert meta['message_id'] == '9001'

    nanoha = (
        '光鸭云盘影视热更频道 🎬 魔法少女奈叶 EXCEEDS Gun Blaze Vengeance (2026) 已更新 '
        '🎭 类型： 电视剧 ⭐ TMDB评分： 7.2 📼 集数： 更新至12集'
    )
    meta = parser(nanoha, '')
    assert meta['display_title'] == '魔法少女奈叶 EXCEEDS Gun Blaze Vengeance'
    assert meta['display_title'].endswith('Vengeance')
    assert '已更新' not in meta['display_title']


def test_v162_labelled_title_and_match_use_parsed_title_not_file_list_noise():
    parser = ns['_entry_metadata']
    meta = parser('剧名：长标题测试 The Complete Title (2026) 已更新 🎭 类型：电视剧', '')
    assert meta['display_title'] == '长标题测试 The Complete Title'

    entry = {
        'display_title': '法律边缘',
        'text': '🎬 法律边缘 (2026) 已更新 分享文件：完全不同的电影名.mkv',
        'year_hint': 2026,
        'tmdb_id': '',
    }
    assert ns['_entry_matches_subscription'](entry, '法律边缘', 2026, 1, '', '') is True
    assert ns['_entry_matches_subscription'](entry, '完全不同的电影名', 2026, 1, '', '') is False


def test_v162_version_contract():
    package = json.loads((ROOT / 'package.v3.json').read_text(encoding='utf-8'))['GuangYaTransferAssistant']
    local = json.loads((ROOT / 'plugins.v3' / 'guangyatransferassistant' / 'plugin.json').read_text(encoding='utf-8'))
    assert package['version'] == '1.6.3' and local['version'] == '1.6.3'
    assert 'plugin_version = "1.6.3"' in text
    assert '_extract_channel_display_title' in text
    assert 'parsed_title if parsed_title else text_value' in text
    assert 'strip()[:420]' in text



def test_v163_weak_episode_filename_fallbacks():
    episode = ns["_episode_numbers"]
    assert episode("[NC-Raws] Some Show - 06 (B-Global 1920x1080 AVC AAC).mkv")[1] == [6]
    assert episode("06.mkv")[1] == [6]
    assert episode("[07].mp4")[1] == [7]
    assert episode("Some.Show.-.08v2.[1080p].mkv")[1] == [8]
    assert episode("Some.Show.2026.2160p.x265.mkv")[1] == []


def test_v163_unparsed_files_are_not_permanently_consumed_and_logs_are_plugin_scoped():
    assert '_data_schema_version = 6' in text
    assert '重新开放 %s 条旧 no_new_episode 记录' in text
    planner = text.split('    def _plan_incremental_files(', 1)[1].split('    @staticmethod\n    def _remember_assets', 1)[0]
    assert 'inferred_episode_by_id' in planner
    assert 'len(video_rows) == total_episode' in planner
    assert 'unparsed_paths' in planner
    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert '未标记为已处理' in flow
    assert '【光鸭转存助手】【分享解析】' in flow
    assert '【光鸭转存助手】【文件识别】' in flow
    assert 'plugin_logs' in text
    assert '光鸭转存助手插件日志' in text
    assert 'api_plugin_logs' in text and 'api_clear_plugin_logs' in text
    assert '这里只显示光鸭转存助手自己的完整日志' in text
