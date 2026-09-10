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


def _split_name_ext_v11226(name: Any) -> Tuple[str, str]:
    text = str(name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not text:
        return "", ""
    path = Path(text)
    suffix = path.suffix
    if suffix and len(suffix) <= 8:
        return path.stem, suffix
    return text, ""


def _episode_tag_v11226(subscribe: Any, path: Any) -> str:
    """生成 SxxExx / SxxExx-Eyy；无法解析集号时仅返回季号或空串。"""
    season, episodes = _episode_numbers(path)
    sub_season = getattr(subscribe, "season", None)
    if season is None and sub_season not in (None, ""):
        try:
            season = int(sub_season)
        except (TypeError, ValueError):
            season = None
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


def _canonical_transfer_name_v11226(
    subscribe: Any,
    original: Any,
    *,
    is_movie: bool = False,
) -> str:
    """剧集名 + 季集号 + 原扩展名；无法解析集号时仅用剧集名。"""
    show = _show_name_v11226(subscribe)
    _, ext = _split_name_ext_v11226(original)
    if not show:
        base = str(original or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        return _safe_name_v11226(base, 240)
    if is_movie:
        return f"{show}{ext}"
    tag = _episode_tag_v11226(subscribe, original)
    if tag:
        return f"{show} {tag}{ext}"
    return f"{show}{ext}"


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

    def _canonical_transfer_name_v11226(self, subscribe: Any, original: Any) -> str:
        return _canonical_transfer_name_v11226(
            subscribe,
            original,
            is_movie=self._is_movie_for_naming_v11226(subscribe),
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
        hint = " ".join(
            str(part or "")
            for part in (
                original,
                source.get("episode_hint"),
                source.get("label"),
                ",".join(str(v) for v in (source.get("resolved_episodes") or [])),
                ",".join(str(v) for v in (source.get("transfer_episodes") or [])),
            )
        )
        desired = self._canonical_transfer_name_v11226(subscribe, hint or original)
        if desired and desired != str(source.get("label") or ""):
            source["label"] = desired
            source_id = str(source.get("id") or "")
            if source_id:
                self._update_source(
                    source_id,
                    requested_name=desired,
                    original_resolved_name=original[:300],
                    naming_style_v11226="show_season_episode",
                )
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【命名v1.12.26】云添加名称：原名=%s 新名=%s",
                original[:180] or "-",
                desired[:220],
            )
        return resolved

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(row or {})
        old_name = str(prepared.get("name") or str(prepared.get("path") or "").rsplit("/", 1)[-1] or "file").strip()
        path_hint = str(prepared.get("path") or old_name)
        desired = self._canonical_transfer_name_v11226(subscribe, path_hint)
        if desired and desired != old_name:
            prepared["name"] = desired
            raw_path = str(prepared.get("path") or old_name).replace("\\", "/")
            parent = raw_path.rsplit("/", 1)[0] if "/" in raw_path else ""
            prepared["path"] = f"{parent}/{desired}" if parent else desired
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【命名v1.12.26】迅雷秒传名称：%s -> %s",
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
                    "【光鸭转存助手】【命名v1.12.26】读取已转存目录失败：%s (%s)",
                    folder_path,
                    str(err)[:180],
                )
                continue
            remote_by_name = {str(getattr(row, "name", "") or ""): row for row in remote_rows}
            used_names = set(remote_by_name.keys())
            for item in group:
                path = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "").replace("\\", "/")
                old_name = path.rsplit("/", 1)[-1]
                desired = self._canonical_transfer_name_v11226(subscribe, path)
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
                            "【光鸭转存助手】【命名v1.12.26】分享落盘后重命名：%s -> %s",
                            old_name[:180],
                            desired[:220],
                        )
                    else:
                        self._plugin_log(
                            "WARNING",
                            "【光鸭转存助手】【命名v1.12.26】分享已成功但重命名未确认：%s -> %s",
                            old_name[:160],
                            desired[:200],
                        )
                except Exception as err:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【命名v1.12.26】分享已成功但重命名异常：%s",
                        str(err)[:220],
                    )
        return renamed


__all__ = [
    "GuangYaChannelTitleRenameV11226Mixin",
    "install_channel_title_rename_v11226",
    "_canonical_transfer_name_v11226",
    "_clean_channel_title_v11226",
]
