from pathlib import Path
import json

legacy_path = Path('plugins.v3/guangyatransferassistant/legacy.py')
text = legacy_path.read_text(encoding='utf-8')
marker = 'def _entry_matches_subscription(\n'
if '_legacy_explicit_seasons_v1111' not in text:
    helper = r'''
def _legacy_explicit_seasons_v1111(values: Iterable[Any]) -> set[int]:
    """频道 matcher 自包含季号提取，兼容插件契约的顶层函数隔离执行。"""
    seasons = set()
    for raw in values or []:
        value = html.unescape(str(raw or ""))
        for matched in re.findall(r"(?i)\bS(?:eason)?[ ._\-]*0*(\d{1,2})(?=E|[^0-9]|$)", value):
            try:
                seasons.add(int(matched))
            except (TypeError, ValueError):
                pass
        for matched in re.findall(r"第\s*0*(\d{1,2})\s*季", value):
            try:
                seasons.add(int(matched))
            except (TypeError, ValueError):
                pass
    return {value for value in seasons if 0 <= value <= 99}


def _legacy_release_title_key_v1111(value: Any, expected_year: Any = None) -> str:
    """频道标题强匹配键：去季集/年份/画质发布信息，但不做包含式模糊匹配。"""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"(?i)\bS(?:eason)?[ ._\-]*0*\d{1,2}(?:[ ._\-]*E(?:pisode)?[ ._\-]*0*\d{1,4})?(?=[^0-9A-Za-z]|$)", " ", text)
    text = re.sub(r"(?i)\b(?:E|EP|Episode)[ ._\-]*0*\d{1,4}\b", " ", text)
    text = re.sub(r"第\s*[0-9一二三四五六七八九十]{1,3}\s*(?:季|集|话)", " ", text)
    year = str(expected_year or "").strip()
    if year and re.fullmatch(r"(?:19|20)\d{2}", year):
        text = re.sub(rf"(?<!\d){re.escape(year)}(?!\d)", " ", text)
    tokens = []
    noise = {
        "2160p", "1080p", "720p", "4k", "8k", "web", "webdl", "webrip", "bluray", "remux",
        "hdtv", "x264", "x265", "h264", "h265", "hevc", "avc", "hdr", "dv", "aac", "dts",
        "complete", "全集", "全季", "中字", "字幕",
    }
    for token in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text):
        lowered = token.casefold().strip()
        if not lowered or lowered in noise:
            continue
        if re.fullmatch(r"(?:2160|1080|720|576|480|264|265)", lowered):
            continue
        tokens.append(lowered)
    return "".join(tokens)


def _legacy_strong_title_match_v1111(expected: Any, actual: Any, expected_year: Any = None) -> bool:
    expected_key = _legacy_release_title_key_v1111(expected, expected_year)
    if not expected_key:
        return False
    candidates = [str(actual or "")]
    candidates.extend(line.strip() for line in str(actual or "").splitlines() if line.strip())
    return any(_legacy_release_title_key_v1111(value, expected_year) == expected_key for value in candidates)


'''
    if marker not in text:
        raise SystemExit('entry matcher marker missing')
    text = text.replace(marker, helper + marker, 1)
text = text.replace(
    'explicit_seasons_v1111([text_value, entry.get("display_title"), entry.get("episode_hint")])',
    '_legacy_explicit_seasons_v1111([text_value, entry.get("display_title"), entry.get("episode_hint")])',
    1,
)
text = text.replace(
    'strong_title_match_v1111(candidate, evidence, expected_year=year)',
    '_legacy_strong_title_match_v1111(candidate, evidence, expected_year=year)',
    1,
)
text = text.replace(
    '"""频道身份门禁：TMDB 冲突硬拒绝；标题强匹配；S02+ 必须有明确季号。"""',
    '"""频道身份门禁：TMDB 冲突硬拒绝；标题强匹配；缺少季号不等于冲突。"""',
    1,
)
legacy_path.write_text(text, encoding='utf-8')

root = Path('tests/v3/guangyatransferassistant')
for path in root.glob('test_*.py'):
    original = path.read_text(encoding='utf-8')
    updated = original
    updated = updated.replace('package["version"] == local["version"] == "1.11.0"', 'package["version"] == local["version"] == "1.11.1"')
    updated = updated.replace('package["version"] == "1.11.0"', 'package["version"] == "1.11.1"')
    updated = updated.replace('local["version"] == "1.11.0"', 'local["version"] == "1.11.1"')
    updated = updated.replace('plugin_version = "1.11.0"\' in entry', 'plugin_version = "1.11.1"\' in entry')
    updated = updated.replace('plugin_version = "1.11.0"\' in texts[ENTRY]', 'plugin_version = "1.11.1"\' in texts[ENTRY]')
    updated = updated.replace("'plugin_version = \"1.11.0\"' in entry_text", "'plugin_version = \"1.11.1\"' in entry_text")
    updated = updated.replace("'plugin_version = \"1.11.0\"' in ENTRY", "'plugin_version = \"1.11.1\"' in ENTRY")
    updated = updated.replace("'build_id = \"20260903-r41\"' in entry_text", "'build_id = \"20260903-r42\"' in entry_text")
    updated = updated.replace("'build_id = \"20260903-r41\"' in ENTRY", "'build_id = \"20260903-r42\"' in ENTRY")
    if path.name == 'test_episode_compat_v171.py':
        updated = updated.replace("'build_id = \"20260903-r41\"' in text", "'build_id = \"20260903-r42\"' in text")
    if updated != original:
        path.write_text(updated, encoding='utf-8')

# 保留原生离线功能的发布契约，同时补充新的媒体身份门禁说明。
package_path = Path('package.v3.json')
package_data = json.loads(package_path.read_text(encoding='utf-8'))
package_item = package_data['GuangYaTransferAssistant']
package_item['description'] = (
    '固定分流与多来源订阅助手：迅雷秒传、光鸭直接转存、Magnet/ED2K 光鸭原生云添加共用集级终态；'
    '新增实际资源媒体身份置信度门禁，明确标题/年份/季号冲突硬拒绝，信息缺失时结合真实文件结构与搜索弱证据继续判断。'
)
package_path.write_text(json.dumps(package_data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

plugin_path = Path('plugins.v3/guangyatransferassistant/plugin.json')
plugin_data = json.loads(plugin_path.read_text(encoding='utf-8'))
plugin_data['description'] = package_item['description']
plugin_path.write_text(json.dumps(plugin_data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
