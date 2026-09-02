"""光鸭转存助手 v1.7.x 剧集弱命名兼容补丁。

处理云盘分享中常见的“集号~画质”文件名，例如：
01~4K.mp4、08～2160p.mkv、22~[4K][HEVC.AAC].mkv，以及
01丨4K.mp4 / 01｜4K.mp4 / 01|4K.mp4 这类频道常见竖线分隔写法。

补丁只在 legacy._episode_numbers 已完全无法识别时启用，并要求分隔符后必须是明确的
画质/编码标记，避免把 01~04.mp4 这类可能表示范围的名字误判为第 1 集。
"""

from __future__ import annotations

import functools
import re
from typing import Any, Optional


_QUALITY_SUFFIX_EPISODE_PATTERN = re.compile(
    r"""(?ix)
    ^\s*0*(\d{1,3})\s*[~～丨|｜]\s*
    [\[【(（]?\s*
    (?:
        (?:4|8)K
        |(?:2160|1080|720|480)[PI]?
        |UHD|FHD|HD
        |HDR(?:10\+?)?
        |DV|DOVI
        |WEB(?:-?DL)?
        |BLU-?RAY|BDREMUX|REMUX
        |HEVC|AVC|AV1|H\.?26[45]|X26[45]
    )
    (?=$|[\s._\-\[\]【】()（）])
    """
)

_UNPARSED_FAILURE_PATTERN = re.compile(
    r"分享内有\s*(\d+)\s*个媒体/字幕文件无法解析集号，未标记为已处理；示例：([^；\n]+)"
)


def extract_quality_suffix_episode(path: Any) -> Optional[int]:
    """从“01~4K / 01丨4K”一类弱文件名中提取集号；不接受纯数字范围。"""
    basename = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    matched = _QUALITY_SUFFIX_EPISODE_PATTERN.search(basename)
    if not matched:
        return None
    episode = int(matched.group(1))
    if 0 < episode <= 500 and episode not in {264, 265, 266}:
        return episode
    return None


def install_episode_filename_compat(legacy_module: Any):
    """热重载安全地替换 legacy._episode_numbers。"""
    current = getattr(legacy_module, "_episode_numbers", None)
    if not callable(current):
        return None
    if getattr(current, "_guangya_quality_suffix_compat", False):
        return current

    @functools.wraps(current)
    def patched(path: Any):
        season, episodes = current(path)
        if episodes:
            return season, episodes
        episode = extract_quality_suffix_episode(path)
        if episode is None:
            return season, episodes
        return season, [episode]

    patched._guangya_quality_suffix_compat = True
    patched._guangya_original_episode_numbers = current
    legacy_module._episode_numbers = patched
    return patched


def collapse_unparsed_failure_notice(text: Any) -> str:
    """同一通知里多条“无法解析集号”错误只保留一个合并摘要。"""
    value = str(text or "")
    matches = list(_UNPARSED_FAILURE_PATTERN.finditer(value))
    if len(matches) <= 1:
        return value

    max_count = max(int(item.group(1)) for item in matches)
    samples = []
    seen = set()
    for item in matches:
        for sample in item.group(2).split("、"):
            sample = sample.strip()
            if sample and sample not in seen:
                seen.add(sample)
                samples.append(sample)

    merged = (
        f"分享内有 {max_count} 个媒体/字幕文件无法解析集号，未标记为已处理；"
        f"示例：{'、'.join(samples[:8]) or '-'}"
    )
    first = matches[0]
    result = value[:first.start()] + merged + value[first.end():]

    # 删除剩余同类片段，同时只吞掉与该片段相邻的一个中文分号。
    while True:
        remaining = list(_UNPARSED_FAILURE_PATTERN.finditer(result))
        if len(remaining) <= 1:
            break
        item = remaining[1]
        start, end = item.start(), item.end()
        if start > 0 and result[start - 1] == "；":
            start -= 1
        elif end < len(result) and result[end] == "；":
            end += 1
        result = result[:start] + result[end:]
    return result


__all__ = [
    "extract_quality_suffix_episode",
    "install_episode_filename_compat",
    "collapse_unparsed_failure_notice",
]
