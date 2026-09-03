"""v1.10.24 资源完成回执：按集占位、单集单视频与电影一次完成。

这一层只收紧“成功资源如何记账”，不改观影/迅雷/光鸭接口协议：
- TV：远端成功写入一个视频后，立即把高置信集号写入既有 media_facts，
  不再等待 Emby 扫描后才认为该集已获得；
- 同一解析批次中，同一集只允许一个视频文件进入实际导入，防止同集多版本同时入库；
- Movie：同一来源只选择一个正片视频；迅雷成功回执一落盘即写电影事实并触发
  MoviePilot 官方订阅完成流程，后续候选不再继续入库。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .episode_fence_v1124 import GuangYaEpisodeFenceV1124Mixin
from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _is_subtitle, _is_video


_MOVIE_AUX_RE_V1124 = re.compile(
    r"(?:^|[/\\\s._\-\[\]()])(?:sample|trailer|teaser|preview|extra|extras|featurette|"
    r"behind[ ._-]?the[ ._-]?scenes|花絮|预告|样片|特辑)(?:$|[/\\\s._\-\[\]()])",
    re.I,
)


def _safe_int_v1124(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


class GuangYaReceiptCompletionV1124Mixin(GuangYaEpisodeFenceV1124Mixin):
    """把真实成功回执提升为即时、持久的订阅进度事实。"""

    build_id = "20260903-r40"

    @staticmethod
    def _resolved_rows_v1124(resolved: Dict[str, Any]) -> List[Dict[str, Any]]:
        bt_info = resolved.get("btResInfo") if isinstance(resolved, dict) else None
        subfiles = bt_info.get("subfiles") if isinstance(bt_info, dict) else None
        if not isinstance(subfiles, list):
            return []
        rows: List[Dict[str, Any]] = []
        for fallback_index, raw in enumerate(subfiles):
            if not isinstance(raw, dict):
                continue
            index = _safe_int_v1124(raw.get("fileIndex"), fallback_index)
            name = str(raw.get("fileName") or raw.get("name") or "").replace("\\", "/").strip()
            rows.append({
                "index": index,
                "name": name,
                "size": _safe_int_v1124(raw.get("fileSize") or raw.get("size"), 0),
                "video": _is_video(name),
                "subtitle": _is_subtitle(name),
            })
        return rows

    @staticmethod
    def _movie_video_rank_v1124(row: Dict[str, Any]) -> Tuple[int, int, int]:
        """在已经通过上游质量门禁的文件中，优先非花絮、较大正片。"""
        name = str(row.get("name") or "")
        normal = 0 if _MOVIE_AUX_RE_V1124.search(name) else 1
        return normal, _safe_int_v1124(row.get("size"), 0), -_safe_int_v1124(row.get("index"), 0)

    def _planner_file_selection(
        self,
        source: Dict[str, Any],
        subscribe: Any,
        resolved: Dict[str, Any],
    ) -> Dict[str, Any]:
        """在既有质量/缺集规划结果之上再做“一个目标只取一个视频”的最终裁剪。"""
        result = dict(super()._planner_file_selection(source, subscribe, resolved) or {})
        if bool(result.get("ambiguous")):
            return result
        selected = [int(value) for value in (result.get("indexes") or [])]
        if not selected:
            return result

        rows = self._resolved_rows_v1124(resolved)
        by_index = {int(row["index"]): row for row in rows}
        selected_rows = [by_index[index] for index in selected if index in by_index]
        diagnostics = list(result.get("diagnostics") or [])

        # 电影：无论来源里带多少版本/花絮，只允许一个正片视频进入任务。
        if self._is_movie_subscription(subscribe):
            videos = [row for row in selected_rows if row.get("video")]
            if len(videos) <= 1:
                return result
            primary = max(videos, key=self._movie_video_rank_v1124)
            primary_index = int(primary["index"])
            primary_parent = self._parent_path(str(primary.get("name") or ""))
            keep = {primary_index}
            for row in selected_rows:
                if not row.get("subtitle"):
                    continue
                if self._parent_path(str(row.get("name") or "")) == primary_parent:
                    keep.add(int(row["index"]))
            removed = [index for index in selected if index not in keep]
            result["indexes"] = [index for index in selected if index in keep]
            diagnostics.append(
                f"电影单资源保护：选中 {primary.get('name') or primary_index}，跳过 {len(removed)} 个其它视频/附件候选"
            )
            result["diagnostics"] = diagnostics
            return result

        # TV：父层已经给出目标集和质量过滤；这里禁止同一集的多个版本同时被选中。
        package_paths = [str(row.get("name") or "") for row in rows if row.get("video") or row.get("subtitle")]
        season_hint = getattr(subscribe, "season", None)
        episode_hint = str(source.get("episode_hint") or "")
        threshold = float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)
        target = {
            int(value) for value in (result.get("episodes") or [])
            if _safe_int_v1124(value, 0) > 0
        }

        video_candidates: List[Tuple[Dict[str, Any], set[int]]] = []
        episode_cache: Dict[int, set[int]] = {}
        for row in selected_rows:
            if not row.get("video"):
                continue
            resolution = resolve_episode(
                str(row.get("name") or ""),
                package_paths=package_paths,
                season_hint=season_hint,
                episode_hint=episode_hint,
            )
            episodes = set(reliable_episode_set(resolution, threshold))
            if target:
                episodes &= target
            episode_cache[int(row["index"])] = episodes
            if episodes:
                video_candidates.append((row, episodes))

        if len(video_candidates) <= 1:
            return result

        # 优先一次覆盖更多缺集的文件；同覆盖数量下取体积较大的已通过质量门禁版本。
        video_candidates.sort(
            key=lambda pair: (
                len(pair[1]),
                _safe_int_v1124(pair[0].get("size"), 0),
                -_safe_int_v1124(pair[0].get("index"), 0),
            ),
            reverse=True,
        )
        claimed: set[int] = set()
        keep_videos: set[int] = set()
        for row, episodes in video_candidates:
            new_episodes = episodes - claimed
            if not new_episodes:
                continue
            keep_videos.add(int(row["index"]))
            claimed.update(episodes)

        if not keep_videos:
            return result

        keep = set(keep_videos)
        kept_by_parent: Dict[str, int] = {}
        for index in keep_videos:
            row = by_index.get(index) or {}
            parent = self._parent_path(str(row.get("name") or ""))
            kept_by_parent[parent] = kept_by_parent.get(parent, 0) + 1

        # 字幕只跟随最终留下的视频/集数，不让被淘汰的视频把整套附件继续带入。
        for row in selected_rows:
            if not row.get("subtitle"):
                continue
            index = int(row["index"])
            resolution = resolve_episode(
                str(row.get("name") or ""),
                package_paths=package_paths,
                season_hint=season_hint,
                episode_hint=episode_hint,
            )
            episodes = set(reliable_episode_set(resolution, threshold))
            if episodes.intersection(claimed):
                keep.add(index)
                continue
            parent = self._parent_path(str(row.get("name") or ""))
            if not episodes and kept_by_parent.get(parent, 0) == 1:
                keep.add(index)

        removed_videos = [
            int(row["index"]) for row in selected_rows
            if row.get("video") and int(row["index"]) not in keep_videos
        ]
        if removed_videos:
            diagnostics.append(
                f"单集单资源保护：已覆盖 {','.join('E%02d' % value for value in sorted(claimed))}；"
                f"跳过 {len(removed_videos)} 个重复集视频版本"
            )
        result["indexes"] = [index for index in selected if index in keep]
        result["episodes"] = sorted(claimed or target)
        result["diagnostics"] = diagnostics
        return result

    def _save_xunlei_state(self, state: Dict[str, Any]) -> None:
        """迅雷单文件成功状态持久化后，立即把该视频转成订阅进度事实。"""
        super()._save_xunlei_state(state)
        items = state.get("items") if isinstance(state, dict) else None
        if not isinstance(items, dict) or not items:
            return

        completed_rows = [
            row for row in items.values()
            if isinstance(row, dict)
            and str(row.get("state") or "") == "completed"
            and _is_video(str(row.get("path") or ""))
        ]
        if not completed_rows:
            return
        latest_ts = max(float(row.get("updated_ts") or 0) for row in completed_rows)
        fresh_rows = [
            row for row in completed_rows
            if float(row.get("updated_ts") or 0) >= latest_ts - 0.01
        ]

        for row in fresh_rows:
            sid = _safe_int_v1124(row.get("subscribe_id"), 0)
            if sid <= 0:
                continue
            subscribe = self._find_subscription(sid)
            if not subscribe:
                continue
            path = str(row.get("path") or getattr(subscribe, "name", "") or "")

            if self._is_movie_subscription(subscribe):
                remember_movie = getattr(self, "_remember_verified_movie_v1121", None)
                if callable(remember_movie):
                    remember_movie(subscribe, "xunlei_receipt_v1124", path)
                else:
                    self._remember_media_facts(
                        subscribe,
                        [{"path": path, "size": 0, "digest": ""}],
                        origin="xunlei_receipt_v1124",
                    )
                completed = bool(self._finish_subscription_if_complete(subscribe))
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【资源回执】#%s 电影正片已成功存入光鸭，立即完成订阅=%s，停止后续资源候选",
                    sid,
                    completed,
                )
                continue

            episodes = sorted({
                _safe_int_v1124(value, 0)
                for value in (row.get("episodes") or [])
                if _safe_int_v1124(value, 0) > 0
            })
            if not episodes:
                continue
            self._remember_episode_facts(subscribe, episodes, origin="xunlei_receipt_v1124")
            self._sync_media_facts_progress(subscribe)
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【资源回执】#%s 已成功存入集数 %s；立即写入订阅进度，后续检索不再选择这些集",
                sid,
                ",".join(f"E{value:02d}" for value in episodes),
            )


__all__ = ["GuangYaReceiptCompletionV1124Mixin"]
