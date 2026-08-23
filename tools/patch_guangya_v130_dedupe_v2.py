from pathlib import Path

src = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = src.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global text
    if old not in text:
        raise SystemExit(f'{label} anchor not found')
    text = text.replace(old, new, 1)


replace_once(
    '''        old = by_key.get(share_key)\n        score = len(entry["text"]) + (600 if entry.get("tmdb_id") else 0) + (300 if entry.get("display_title") else 0)\n        old_score = len(str((old or {}).get("text") or "")) + (600 if (old or {}).get("tmdb_id") else 0) + (300 if (old or {}).get("display_title") else 0)\n        if not old or score > old_score:\n            by_key[share_key] = entry\n''',
    '''        entry_key = _entry_process_key(entry) or share_key\n        old = by_key.get(entry_key)\n        score = len(entry["text"]) + (600 if entry.get("tmdb_id") else 0) + (300 if entry.get("display_title") else 0)\n        old_score = len(str((old or {}).get("text") or "")) + (600 if (old or {}).get("tmdb_id") else 0) + (300 if (old or {}).get("display_title") else 0)\n        if not old or score > old_score:\n            by_key[entry_key] = entry\n''',
    'message-aware extraction dedupe',
)

replace_once(
    '''                    for item in found:\n                        key = _share_identity(item.get("share_url") or "")\n                        if not key or key in source_seen:\n                            continue\n                        source_seen.add(key)\n''',
    '''                    for item in found:\n                        key = _entry_process_key(item) or _share_identity(item.get("share_url") or "")\n                        if not key or key in source_seen:\n                            continue\n                        source_seen.add(key)\n''',
    'source message-aware dedupe',
)
replace_once(
    '''                    fresh_keys = {_share_identity(item.get("share_url") or "") for item in source_entries}\n                    for old in previous_items:\n                        if old.get("source_label") != label:\n                            continue\n                        key = _share_identity(old.get("share_url") or "")\n                        if key and key not in fresh_keys:\n''',
    '''                    fresh_keys = {_entry_process_key(item) or _share_identity(item.get("share_url") or "") for item in source_entries}\n                    for old in previous_items:\n                        if old.get("source_label") != label:\n                            continue\n                        key = _entry_process_key(old) or _share_identity(old.get("share_url") or "")\n                        if key and key not in fresh_keys:\n''',
    'stale message-aware dedupe',
)
replace_once(
    '''        # 新鲜条目优先，热更频道优先；同一分享跨频道只保留最佳条目。\n        all_entries.sort(key=lambda item: (1 if item.get("stale") else 0, int(item.get("priority") or 0), -len(str(item.get("text") or ""))))\n        entries: List[Dict[str, Any]] = []\n        seen = set()\n        for item in all_entries:\n            key = _share_identity(item.get("share_url") or "")\n            if not key or key in seen:\n                continue\n            seen.add(key)\n            entries.append(item)\n''',
    '''        # 当前抓取优先、热更频道优先；同一消息+同一分享只保留一条，新消息即使复用旧链接也保留。\n        all_entries.sort(key=lambda item: (1 if item.get("stale") else 0, int(item.get("priority") or 0), -len(str(item.get("text") or ""))))\n        entries: List[Dict[str, Any]] = []\n        seen = set()\n        for item in all_entries:\n            key = _entry_process_key(item) or _share_identity(item.get("share_url") or "")\n            if not key or key in seen:\n                continue\n            seen.add(key)\n            entries.append(item)\n''',
    'global message-aware dedupe',
)
replace_once(
    '        logger.info("【光鸭转存助手】频道刷新完成，识别分享 %s 个（新鲜 %s / 旧缓存 %s），错误 %s 个", len(entries), fresh_count, stale_count, len(errors))\n',
    '        logger.info("【光鸭转存助手】频道刷新完成，识别消息/分享 %s 个（当前抓取 %s / 回退缓存 %s），错误 %s 个", len(entries), fresh_count, stale_count, len(errors))\n',
    'refresh log wording',
)
replace_once(
    '                {"component": "VCardText", "text": "显示链接类型、TMDB/集数提示、缓存新鲜度及匹配原因；最多显示 150 条。"},\n',
    '                {"component": "VCardText", "text": "显示链接类型、TMDB/集数提示、当前抓取/回退缓存状态及匹配原因；同一链接出现在新消息中会作为新条目处理，最多显示 150 条。"},\n',
    'page wording',
)

replace_once(
    '''        self.refresh_channels(force=False)\n        entries = list((self.get_data("channel_index") or {}).get("items") or [])\n        matched_pairs = []\n''',
    '''        self.refresh_channels(force=False)\n        # 每轮先以媒体库为事实源同步当前目标范围，频道没有新链接时也能去掉已入库重复集。\n        self._sync_media_library_progress(subscribe)\n        entries = list((self.get_data("channel_index") or {}).get("items") or [])\n        matched_pairs = []\n''',
    'pre-match media sync',
)
replace_once(
    '''        channel_state = self._channel_state_for_subscription(subscribe, [item for item, _ in matched_pairs])\n        self._sync_channel_episode_floor(subscribe, channel_state)\n        self._sync_media_library_progress(subscribe)\n''',
    '''        channel_state = self._channel_state_for_subscription(subscribe, [item for item, _ in matched_pairs])\n        if self._sync_channel_episode_floor(subscribe, channel_state):\n            # 频道把目标集数向上扩展后，再同步一次媒体库新扩展区间。\n            self._sync_media_library_progress(subscribe)\n''',
    'post-floor media sync',
)

src.write_text(text, encoding='utf-8')

test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
tests = test_path.read_text(encoding='utf-8')
addition = r'''


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
    assert '当前抓取' in text and '回退缓存' in text
'''
if 'test_same_share_in_new_message_is_kept_as_new_entry' not in tests:
    tests += addition

test_path.write_text(tests, encoding='utf-8')
