"""v1.12.26 频道标题清洗 + 转存后「剧集名 + 季集」命名。

1. 兼容 tgm 合集里常见的非热更模板：
   - `名称：标题(2026） 4K 更新至11集`
   - `[剧集·光鸭] 标题 (2022)`
   清理画质/更新尾巴与频道标签前缀，避免强标题匹配失败后直接跳过转存。
2. 转存落盘命名改为：`剧集名 SxxExx.ext`（多集 `SxxExx-Eyy`）；电影仅用剧名。
   覆盖迅雷秒传、Magnet/ED2K 云添加提交名，以及光鸭分享落盘后的远端 rename。
"""
from __future__ import annotations

import functools
import html
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .legacy import _episode_numbers, _is_subtitle, _is_video, _safe_relative_path


_FORBIDDEN_NAME_V11226 = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
_YEAR_TAIL_V11226 = re.compile(
    r"[（(]\s*(?:19\d{2}|20\d{2})\s*[）)].*$"
)
_BRACKET_TAG_V11226 = re.compile(r"【[^】]{0,80}】")
_HDHIVE_PREFIX_V11226 = re.compile(
    r"^\[\s*(?:剧集|电影|动漫|动画|综艺)[^\]]{0,40}\]\s*",
    re.I,
)
_QUALITY_TAIL_V11226 = re.compile(
    r"(?i)\s*(?:"
    r"4K|8K|2160p|1080p|720p|480p|HDR10\+?|DV|Dolby|Atmos|"
    r"WEB-?DL|WEBRip|BluRay|REMUX|H\.?265|H\.?264|HEVC|AAC|DDP|"
    r"更新至\s*\d+\s*集|更新到\s*\d+\s*集|更至\s*\d+\s*集|"
    r"全\s*\d+\s*集|全季|全集|剧情|奇幻|古装|喜剧|动作|爱情|"
    r"高码率|内封|简繁英"
    r").*$"
)
_HDHIVE_LINE_V11226 = re.compile(
    r"(?im)^\s*\[\s*(?:剧集|电影|动漫|动画|综艺)[^\]]{0,40}\]\s*([^\n]{2,240})\s*$"
)


def _safe_name_v11226(value: Any, limit: int = 120) -> str:
    text = _FORBIDDEN_NAME_V11226.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-_")
    return text[: max(1, int(limit or 120))].strip()


def _show_name_v11226(subscribe: Any) -> str:
    raw = str(getattr(subscribe, "name", "") or "").strip()
    raw = re.sub(r"\s*[（(]\s*(?:19\d{2}|20\d{2})\s*[）)]\s*$", "", raw).strip()
    return _safe_name_v11226(raw)


def _strip_media_folder_suffix_v11226(value: Any) -> str:
    """从 MoviePilot 目标作品目录提取纯作品名，不把 Season / TMDB 标记带进文件名。"""
    text = str(value or "").strip()
    text = re.sub(r"\s*[{[]\s*(?:tmdb|tvdb|imdb)?id?\s*=\s*[^}\]]+[}\]]\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*[（(]\s*(?:19\d{2}|20\d{2})\s*[）)]\s*$", "", text).strip()
    return _safe_name_v11226(text)


def _is_season_folder_v11226(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(
        r"(?i)(?:season\s*\d{1,3}|s\d{1,3}|第\s*\d{1,3}\s*季|specials?)",
        text,
    ))


def _split_name_ext_v11226(name: Any) -> Tuple[str, str]:
    text = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not text:
        return "", ""
    path = Path(text)
    suffix = path.suffix
    if suffix and len(suffix) <= 8:
        return path.stem, suffix
    return text, ""


def _episode_tag_v11226(
    subscribe: Any,
    path: Any,
    explicit_episodes: Optional[Iterable[Any]] = None,
) -> str:
    """生成 SxxExx / SxxExx-Eyy；优先文件真实集号，弱命名时使用 planner 已解析集号。"""
    season, episodes = _episode_numbers(path)
    sub_season = getattr(subscribe, "season", None)
    if season is None and sub_season not in (None, ""):
        try:
            season = int(sub_season)
        except (TypeError, ValueError):
            season = None
    if not episodes and explicit_episodes:
        parsed: List[int] = []
        for raw in explicit_episodes:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                parsed.append(value)
        episodes = sorted(set(parsed))
    if not episodes:
        if season is None:
            return ""
        return f"S{int(season):02d}"
    values = sorted({int(ep) for ep in episodes if int(ep) > 0})
    if not values:
        return ""
    if season is None:
        season = 1
    if len(values) == 1:
        return f"S{int(season):02d}E{values[0]:02d}"
    return f"S{int(season):02d}E{values[0]:02d}-E{values[-1]:02d}"


def _release_tail_v11226(
    original: Any,
    *,
    explicit_episodes: Optional[Iterable[Any]] = None,
    year: Any = None,
    is_movie: bool = False,
) -> str:
    """保留原资源季集号之后的清晰度/来源/编码/音轨/发布组，不保留旧作品名和旧集号。"""
    stem, _ext = _split_name_ext_v11226(original)
    text = str(stem or "").strip()
    if not text:
        return ""

    if is_movie:
        year_text = str(year or "").strip()
        if year_text and re.fullmatch(r"(?:19|20)\d{2}", year_text):
            matched = re.search(rf"(?<!\d){re.escape(year_text)}(?!\d)", text)
            if matched:
                text = text[matched.end():]
        # 没有年份锚点时宁可不剪标题，避免把错误标题当发布信息。
        elif not re.search(r"(?i)(?:2160p|1080p|720p|WEB[- .]?DL|WEBRip|BluRay|REMUX|HDR|DV|HEVC|H[ .]?26[45]|x26[45])", text):
            return ""
    else:
        matched = re.search(
            r"(?i)S\d{1,3}[ ._-]*E\d{1,4}(?:[ ._-]*(?:-|~|to)[ ._-]*E?\d{1,4})?",
            text,
        )
        if matched:
            text = text[matched.end():]
        else:
            # 03.2160p / E03.WEB-DL 等弱命名，只有 planner 已确认唯一集号时才移除开头集号。
            explicit = []
            for raw in explicit_episodes or []:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    explicit.append(value)
            explicit = sorted(set(explicit))
            if len(explicit) == 1:
                ep = explicit[0]
                weak = re.match(rf"(?i)^\s*(?:EP?|第)?0*{ep}(?:集|话)?(?=$|[ ._\-]+)", text)
                if weak:
                    text = text[weak.end():]

    text = re.sub(r"^[\s._\-–—]+", "", text)
    text = re.sub(r"[\s._\-–—]+$", "", text)
    text = _FORBIDDEN_NAME_V11226.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-_")
    return text[:180].strip()


def _canonical_transfer_name_v11226(
    subscribe: Any,
    original: Any,
    *,
    is_movie: bool = False,
    show_name: str = "",
    explicit_episodes: Optional[Iterable[Any]] = None,
) -> str:
    """MP 识别作品名 + 季集号 + 原资源发布信息 + 原扩展名。"""
    show = _safe_name_v11226(show_name) or _show_name_v11226(subscribe)
    _, ext = _split_name_ext_v11226(original)
    if not show:
        base = str(original or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        return _safe_name_v11226(base, 240)

    tail = _release_tail_v11226(
        original,
        explicit_episodes=explicit_episodes,
        year=getattr(subscribe, "year", None),
        is_movie=is_movie,
    )
    if is_movie:
        core = show
    else:
        tag = _episode_tag_v11226(subscribe, original, explicit_episodes=explicit_episodes)
        core = f"{show} - {tag}" if tag else show
    if tail:
        core = f"{core} - {tail}"
    return f"{_safe_name_v11226(core, 230)}{ext}"

def _clean_channel_title_v11226(value: Any) -> str:
    """剥离频道模板噪声，只保留可强匹配的作品标题。"""
    title = html.unescape(str(value or "")).strip()
    title = re.sub(r"^[\s🎬🎞🎥📺]+", "", title).strip()
    title = re.sub(r"^(?:电影|剧集|电视剧|动漫|动画)\s*[：:]\s*", "", title, flags=re.I).strip()
    title = _HDHIVE_PREFIX_V11226.sub("", title).strip()
    title = _BRACKET_TAG_V11226.sub(" ", title)
    title = re.sub(r"\s+", " ", title).strip()
    # 年份后的画质/更新尾巴一律丢掉，再去掉年份本身（匹配键不需要年份）。
    if _YEAR_TAIL_V11226.search(title):
        title = _YEAR_TAIL_V11226.sub("", title).strip()
    else:
        title = _QUALITY_TAIL_V11226.sub("", title).strip()
    title = re.sub(r"\s*(?:已?更新|更新中|已?完结|完结|全集|全季)\s*$", "", title, flags=re.I).strip()
    return title[:300]


def _extract_channel_title_v11226(raw: Any, fallback) -> str:
    text = str(raw or "")
    labelled = re.search(r"(?im)(?:^|\n)\s*(?:名称|片名|剧名|标题)\s*[：:]\s*([^\n]{2,320})", text)
    if labelled:
        cleaned = _clean_channel_title_v11226(labelled.group(1))
        if cleaned:
            return cleaned
    hdhive = _HDHIVE_LINE_V11226.search(text)
    if hdhive:
        cleaned = _clean_channel_title_v11226(hdhive.group(1))
        if cleaned:
            return cleaned
    cleaned = _clean_channel_title_v11226(fallback(text) if callable(fallback) else "")
    if cleaned:
        return cleaned
    return _clean_channel_title_v11226(text)


def install_channel_title_rename_v11226(legacy_module: Any) -> None:
    """热重载安全地增强频道标题解析，不改动分享链接识别。"""
    current_clean = getattr(legacy_module, "_clean_channel_display_title", None)
    current_extract = getattr(legacy_module, "_extract_channel_display_title", None)
    if not callable(current_clean) or not callable(current_extract):
        return
    if getattr(current_extract, "_guangya_channel_title_v11226", False):
        return

    original_clean = current_clean
    original_extract = current_extract

    @functools.wraps(original_clean)
    def patched_clean(value: Any) -> str:
        cleaned = _clean_channel_title_v11226(original_clean(value))
        return cleaned or _clean_channel_title_v11226(value)

    @functools.wraps(original_extract)
    def patched_extract(value: Any) -> str:
        return _extract_channel_title_v11226(value, original_extract)

    patched_extract._guangya_channel_title_v11226 = True
    patched_extract._guangya_original_extract_channel_title = original_extract
    legacy_module._clean_channel_display_title = patched_clean
    legacy_module._extract_channel_display_title = patched_extract


class GuangYaChannelTitleRenameV11226Mixin:
    """频道标题兼容 + 转存文件名改为剧集名+季集。"""

    plugin_version = "1.12.26"
    build_id = "20260910-r73"

    def _is_movie_for_naming_v11226(self, subscribe: Any) -> bool:
        checker = getattr(self, "_is_movie_subscription", None)
        if callable(checker):
            try:
                return bool(checker(subscribe))
            except Exception:
                return False
        media_type = str(getattr(subscribe, "type", "") or getattr(subscribe, "media_type", "") or "").lower()
        return media_type in {"movie", "movies", "电影"}

    def _mp_recognized_show_name_v11226(self, subscribe: Any) -> str:
        """优先使用 MoviePilot 已计算的目标作品目录，避免转存助手自行猜作品名。"""
        try:
            target = str(self._target_path(subscribe) or "").replace("\\", "/").rstrip("/")
        except Exception:
            target = ""
        if target:
            parts = [part.strip() for part in target.split("/") if part.strip()]
            for part in reversed(parts):
                if _is_season_folder_v11226(part):
                    continue
                candidate = _strip_media_folder_suffix_v11226(part)
                if candidate:
                    return candidate
        return _show_name_v11226(subscribe)

    def _canonical_transfer_name_v11226(
        self,
        subscribe: Any,
        original: Any,
        *,
        explicit_episodes: Optional[Iterable[Any]] = None,
    ) -> str:
        return _canonical_transfer_name_v11226(
            subscribe,
            original,
            is_movie=self._is_movie_for_naming_v11226(subscribe),
            show_name=self._mp_recognized_show_name_v11226(subscribe),
            explicit_episodes=explicit_episodes,
        )

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        resolved = dict(super()._resolve_offline_source(source, subscribe) or {})
        original = str(
            source.get("original_resolved_name")
            or resolved.get("resolved_name")
            or source.get("resolved_name")
            or source.get("name")
            or source.get("label")
            or ""
        ).strip()
        explicit_episodes = (
            source.get("transfer_episodes")
            or source.get("resolved_episodes")
            or source.get("target_episodes")
            or []
        )
        desired = self._canonical_transfer_name_v11226(
            subscribe,
            original,
            explicit_episodes=explicit_episodes,
        )
        if desired and desired != str(source.get("label") or ""):
            source["label"] = desired
            source_id = str(source.get("id") or "")
            if source_id:
                self._update_source(
                    source_id,
                    requested_name=desired,
                    original_resolved_name=original[:300],
                    naming_style_v11226="mp_title_episode_release",
                )
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【命名】云添加名称：原名=%s 新名=%s",
                original[:180] or "-",
                desired[:220],
            )
        return resolved

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(row or {})
        old_name = str(prepared.get("name") or str(prepared.get("path") or "").rsplit("/", 1)[-1] or "file").strip()
        path_hint = str(prepared.get("path") or old_name)
        explicit_episodes = (
            prepared.get("transfer_episodes")
            or prepared.get("resolved_episodes")
            or prepared.get("episodes")
            or []
        )
        desired = self._canonical_transfer_name_v11226(
            subscribe,
            path_hint,
            explicit_episodes=explicit_episodes,
        )
        if desired and desired != old_name:
            prepared["name"] = desired
            raw_path = str(prepared.get("path") or old_name).replace("\\", "/")
            parent = raw_path.rsplit("/", 1)[0] if "/" in raw_path else ""
            prepared["path"] = f"{parent}/{desired}" if parent else desired
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【命名】迅雷秒传名称：%s -> %s",
                old_name[:180],
                desired[:220],
            )
        # 跳过 v1.12.24 的“识别文件夹前缀”，避免叠成“目录 - 剧集名 SxxExx”。
        from .auto_recovery_v11224 import GuangYaAutoRecoveryV11224Mixin

        parent = super(GuangYaAutoRecoveryV11224Mixin, self)
        return dict(parent._rapid_transfer_xunlei_file(subscribe, prepared) or {})

    def _rename_restored_media_v11224(
        self,
        subscribe: Any,
        save_path: str,
        items: Iterable[Dict[str, Any]],
    ) -> int:
        """覆盖 v1.12.24 前缀命名：落盘后改为剧集名 + 季集。"""
        if subscribe is None:
            return 0
        client, api = self._get_guangya_runtime()
        if not client or not api or not callable(getattr(client, "rename", None)):
            return 0
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items or []:
            path = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            if not (_is_video(path) or _is_subtitle(path)):
                continue
            groups.setdefault(str(item.get("target_parent") or ""), []).append(dict(item))
        renamed = 0
        base = str(save_path or "/").replace("\\", "/").rstrip("/") or "/"
        rename_ok = getattr(self, "_rename_ok_v11224", None)
        for relative_parent, group in groups.items():
            parent = _safe_relative_path(relative_parent)
            folder_path = (base.rstrip("/") + ("/" + parent if parent else "")) or "/"
            try:
                folder = api.get_item(Path(folder_path)) if callable(getattr(api, "get_item", None)) else None
                if folder is None:
                    continue
                remote_rows = list(api.list(folder) or []) if callable(getattr(api, "list", None)) else []
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【命名】读取已转存目录失败：%s (%s)",
                    folder_path,
                    str(err)[:180],
                )
                continue
            remote_by_name = {str(getattr(row, "name", "") or ""): row for row in remote_rows}
            used_names = set(remote_by_name.keys())
            for item in group:
                path = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "").replace("\\", "/")
                old_name = path.rsplit("/", 1)[-1]
                explicit_episodes = (
                    item.get("transfer_episodes")
                    or item.get("resolved_episodes")
                    or item.get("episodes")
                    or []
                )
                desired = self._canonical_transfer_name_v11226(
                    subscribe,
                    path,
                    explicit_episodes=explicit_episodes,
                )
                if not desired or desired == old_name:
                    continue
                if desired in used_names and desired != old_name:
                    stem, ext = _split_name_ext_v11226(desired)
                    index = 2
                    candidate = desired
                    while candidate in used_names:
                        candidate = f"{stem} ({index}){ext}"
                        index += 1
                    desired = candidate
                remote = remote_by_name.get(old_name)
                file_id = str(getattr(remote, "fileid", "") or "") if remote is not None else ""
                if not file_id:
                    continue
                try:
                    response = client.rename(file_id, desired)
                    ok = bool(rename_ok(response)) if callable(rename_ok) else True
                    if ok:
                        renamed += 1
                        used_names.discard(old_name)
                        used_names.add(desired)
                        self._plugin_log(
                            "INFO",
                            "【光鸭转存助手】【命名】分享落盘后重命名：%s -> %s",
                            old_name[:180],
                            desired[:220],
                        )
                    else:
                        self._plugin_log(
                            "WARNING",
                            "【光鸭转存助手】【命名】分享已成功但重命名未确认：%s -> %s",
                            old_name[:160],
                            desired[:200],
                        )
                except Exception as err:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【命名】分享已成功但重命名异常：%s",
                        str(err)[:220],
                    )
        return renamed


__all__ = [
    "GuangYaChannelTitleRenameV11226Mixin",
    "install_channel_title_rename_v11226",
    "_canonical_transfer_name_v11226",
    "_clean_channel_title_v11226",
]
