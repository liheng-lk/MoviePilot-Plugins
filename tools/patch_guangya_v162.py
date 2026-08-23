from pathlib import Path
import json

ROOT = Path('.')
SRC = ROOT / 'plugins.v3' / 'guangyatransferassistant' / '__init__.py'
TEST = ROOT / 'tests' / 'v3' / 'guangyatransferassistant' / 'test_plugin_contract.py'
PACKAGE = ROOT / 'package.v3.json'
PLUGIN = ROOT / 'plugins.v3' / 'guangyatransferassistant' / 'plugin.json'

text = SRC.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'{label} anchor not found')
    text = text.replace(old, new, 1)


replace_once('    plugin_version = "1.6.1"\n', '    plugin_version = "1.6.2"\n', 'plugin version')

html_anchor = '''def _html_to_text(fragment: str) -> str:\n    \"\"\"HTML 转文本时保留消息换行，避免相邻字段粘连。\"\"\"\n    value = re.sub(r\"<script\\b[^>]*>.*?</script>\", \" \", str(fragment or \"\"), flags=re.I | re.S)\n    value = re.sub(r\"<style\\b[^>]*>.*?</style>\", \" \", value, flags=re.I | re.S)\n    value = re.sub(r\"(?i)<br\\s*/?>|</(?:div|p|li|section|article|blockquote)\\s*>\", \"\\n\", value)\n    value = re.sub(r\"<[^>]+>\", \" \", value)\n    value = html.unescape(value)\n    lines = [re.sub(r\"\\s+\", \" \", line).strip() for line in value.splitlines()]\n    return \"\\n\".join(line for line in lines if line)\n\n\n'''
if html_anchor not in text:
    raise SystemExit('html helper anchor not found')
helpers = html_anchor + r'''_CHANNEL_META_BOUNDARY = re.compile(
    r"(?=\s*(?:🎭|⭐|🖥|📺|📼|📦|👤|🔗|📝|类型\s*[：:]|TMDB(?:\s*ID)?\s*[：:#]|"
    r"TMDB评分\s*[：:]|画质\s*[：:]|质量\s*[：:]|集数\s*[：:]|大小\s*[：:]|分享\s*[：:]|简介\s*[：:]|$))",
    re.I,
)


def _clean_channel_display_title(value: Any) -> str:
    """清理频道标题末尾年份/更新状态，但保留完整中英日韩标题。"""
    title = html.unescape(str(value or "")).strip()
    title = re.sub(r"^[\s🎬🎞🎥📺]+", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    # 新热更模板常见：标题 (2026) 已更新 / 标题（2026）完结。
    title = re.sub(
        r"\s*[（(]\s*(?:19\d{2}|20\d{2})\s*[）)]\s*(?:已?更新|更新中|已?完结|完结|全集|全季)?\s*$",
        "",
        title,
        flags=re.I,
    ).strip()
    title = re.sub(r"\s*(?:已?更新|更新中|已?完结|完结)\s*$", "", title, flags=re.I).strip()
    return title[:300]


def _extract_channel_display_title(text: Any) -> str:
    """兼容“名称：xxx”和“🎬 xxx (2026) 已更新”两类频道标题模板。"""
    raw = str(text or "")
    # 传统字段格式。允许标题后同一行继续跟元数据 emoji。
    labelled = re.search(r"(?im)(?:^|\n)\s*(?:名称|片名|剧名|标题)\s*[：:]\s*([^\n]{2,320})", raw)
    if labelled:
        candidate = _CHANNEL_META_BOUNDARY.split(labelled.group(1), maxsplit=1)[0]
        cleaned = _clean_channel_display_title(candidate)
        if cleaned:
            return cleaned

    # 新版影视热更频道：频道名可能与 🎬 标题处于同一文本行。
    emoji = re.search(r"🎬\s*([^\n]{2,360})", raw)
    if emoji:
        candidate = _CHANNEL_META_BOUNDARY.split(emoji.group(1), maxsplit=1)[0]
        cleaned = _clean_channel_display_title(candidate)
        if cleaned:
            return cleaned

    # 保守兜底：只接受带年份、且不是明显元数据字段的独立行，避免把分享文件名误当标题。
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or re.match(r"^(?:类型|TMDB|画质|质量|集数|大小|分享|简介)\s*[：:]", line, re.I):
            continue
        if not re.search(r"[（(](?:19\d{2}|20\d{2})[）)]", line):
            continue
        candidate = _CHANNEL_META_BOUNDARY.split(line, maxsplit=1)[0]
        cleaned = _clean_channel_display_title(candidate)
        if cleaned and "光鸭云盘影视热更频道" not in cleaned:
            return cleaned
    return ""


'''
text = text.replace(html_anchor, helpers, 1)

old_meta = '''    tmdb_match = TMDB_PATTERN.search(text)\n    name_match = re.search(r\"(?im)(?:^|\\n)\\s*(?:名称|片名|剧名)\\s*[：:]\\s*([^\\n]{2,180})\", text)\n    display_title = name_match.group(1).strip() if name_match else \"\"\n'''
new_meta = '''    tmdb_match = TMDB_PATTERN.search(text)\n    display_title = _extract_channel_display_title(text)\n'''
replace_once(old_meta, new_meta, 'metadata title parser')

replace_once(
    '    year_match = re.search(r"\\b(19\\d{2}|20\\d{2})\\b", display_title or text)\n',
    '    year_match = re.search(r"\\b(19\\d{2}|20\\d{2})\\b", text)\n',
    'year hint source',
)

old_haystack = '''    haystack = _normalize_media_text("\\n".join(filter(None, [str(entry.get("display_title") or ""), text_value])))\n'''
new_haystack = '''    parsed_title = str(entry.get("display_title") or "").strip()\n    # 已成功解析频道标题时，只用标题做标题匹配；避免字幕/文件列表中的其它片名造成误命中。\n    haystack = _normalize_media_text(parsed_title if parsed_title else text_value)\n'''
replace_once(old_haystack, new_haystack, 'matching title source')

old_years = '''        years = {int(value) for value in re.findall(r"\\b(19\\d{2}|20\\d{2})\\b", str(entry.get("display_title") or "") or text_value)}\n'''
new_years = '''        hinted_year = entry.get("year_hint")\n        years = {int(hinted_year)} if hinted_year else {int(value) for value in re.findall(r"\\b(19\\d{2}|20\\d{2})\\b", text_value)}\n'''
replace_once(old_years, new_years, 'matching year hint')

replace_once('            snippet = re.sub(r"\\s+", " ", snippet).strip()[:160]\n',
             '            snippet = re.sub(r"\\s+", " ", snippet).strip()[:420]\n',
             'resource snippet length')

SRC.write_text(text, encoding='utf-8')

package = json.loads(PACKAGE.read_text(encoding='utf-8'))
entry = package['GuangYaTransferAssistant']
entry['version'] = '1.6.2'
entry['description'] = '光鸭订阅固定分流：兼容影视热更频道 🎬 标题模板并保留完整中英日韩标题，修复标题解析失败/截断导致的订阅未匹配；保留 S00 同步、人工防重门禁和完整可靠性闭环。'
history = entry.setdefault('history', {})
entry['history'] = {
    'v1.6.2': '标题解析修复：兼容“🎬 标题 (年份) 已更新”影视热更频道模板及与频道名同一行的结构，保留完整中英日韩标题并清理年份/更新状态后再匹配；成功解析标题时不再用分享文件列表文本做标题兜底，降低误匹配；频道资源详情增加更长原文预览。',
    **history,
}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

plugin = json.loads(PLUGIN.read_text(encoding='utf-8'))
plugin['version'] = '1.6.2'
plugin['description'] = '固定转存订阅：修复影视热更频道 🎬 标题解析、完整多语言标题匹配与资源详情截断，并保留 S00/防重/任务审计完整闭环。'
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

tests = TEST.read_text(encoding='utf-8').replace('1.6.1', '1.6.2')
addition = r'''


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
    assert package['version'] == '1.6.2' and local['version'] == '1.6.2'
    assert 'plugin_version = "1.6.2"' in text
    assert '_extract_channel_display_title' in text
    assert 'parsed_title if parsed_title else text_value' in text
    assert 'strip()[:420]' in text
'''
if 'test_v162_emoji_channel_title_parser_keeps_full_titles' not in tests:
    tests += addition
TEST.write_text(tests, encoding='utf-8')

print('GuangYa v1.6.2 title parser patch applied')
