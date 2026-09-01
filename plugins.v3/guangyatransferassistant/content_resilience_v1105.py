"""v1.10.5 频道分享追更与文件语义自愈。

修复三个会造成真实漏转存的边界：
- MoviePilot 当前 total_episode 落后于分享内容时，明确的分享文件集号可以只向上抬高目标范围；
- 片头/片尾/OP/ED/Trailer/Sample 等辅助视频不再被当成“无法解析集号”的正片阻塞整条分享；
- 旧版 processed_entries 没有记录处理时的目标集数，升级后对仍缺集的订阅重新检查一次；
  新记录保存 target_total，后续只有目标总集数继续向上增长时才自动重新开放。

本层只影响光鸭分享的文件规划与去重寿命，不改变资源规则、MoviePilot 下载门禁、
观影/迅雷、Magnet/ED2K 或 cloudcollection 执行链。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.db.oper.subscribe import SubscribeOper

from .legacy import _episode_numbers, _is_video, _safe_relative_path


_TARGET_BOUND_PROCESSED_STATES = {
    "processed",
    "transferred",
    "synced",
    "no_new_episode",
    "legacy_synced",
}

_AUXILIARY_DIR_NAMES = {
    "片头尾",
    "片头片尾",
    "片头",
    "片尾",
    "opening",
    "ending",
    "op",
    "ed",
    "trailer",
    "trailers",
    "sample",
    "samples",
    "preview",
    "previews",
}

_AUXILIARY_STEM_RE = re.compile(
    r"^(?:片头|片尾|片头曲|片尾曲|opening|ending|op\d*|ed\d*|trailer\d*|sample\d*|preview\d*|pv\d*)$",
    re.I,
)


def _safe_int_v1105(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_auxiliary_media_v1105(path: Any) -> bool:
    """只识别强语义片头/片尾/预告/样片，避免把正常特别篇误过滤。"""
    normalized = _safe_relative_path(path).replace("\\", "/").strip()
    if not normalized:
        return False
    parts = [part.strip().lower() for part in normalized.split("/") if part.strip()]
    if not parts:
        return False
    if any(part in _AUXILIARY_DIR_NAMES for part in parts[:-1]):
        return True
    basename = parts[-1]
    stem = re.sub(r"\.[a-z0-9]{2,6}$", "", basename, flags=re.I).strip()
    stem = re.sub(r"[\s._\-]+", "", stem)
    return bool(_AUXILIARY_STEM_RE.fullmatch(stem))


class GuangYaContentResilienceV1105Mixin:
    """最终分享文件语义与 processed-entry 生命周期补丁。"""

    build_id = "20260901-r16"

    @staticmethod
    def _is_tv_subscription_v1105(subscribe: Any) -> bool:
        if subscribe is None:
            return False
        media_type = str(getattr(subscribe, "type", "") or "").lower()
        return (
            "tv" in media_type
            or "电视剧" in str(getattr(subscribe, "type", "") or "")
            or getattr(subscribe, "season", None) not in (None, 0)
        )

    def _sync_share_episode_floor_v1105(self, probe: Dict[str, Any], subscribe: Any) -> bool:
        """从分享内可明确解析的正片集号只向上扩展 MoviePilot 追更目标。"""
        if not self._is_tv_subscription_v1105(subscribe):
            return False
        sid = _safe_int_v1105(getattr(subscribe, "id", 0), 0)
        current_total = max(0, _safe_int_v1105(getattr(subscribe, "total_episode", 0), 0))
        if not sid:
            return False

        raw_season = getattr(subscribe, "season", None)
        wanted_season: Optional[int]
        try:
            wanted_season = int(raw_season) if raw_season not in (None, "") else None
        except (TypeError, ValueError):
            wanted_season = None

        episodes = set()
        for raw in probe.get("files") or []:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            path = _safe_relative_path(raw.get("relative_path") or raw.get("name") or "")
            if not path or not _is_video(path) or is_auxiliary_media_v1105(path):
                continue
            file_season, values = _episode_numbers(path)
            if wanted_season is not None:
                if file_season is not None and int(file_season) != wanted_season:
                    continue
                if wanted_season == 0 and file_season is None:
                    continue
            for value in values:
                episode = _safe_int_v1105(value, 0)
                if 0 < episode <= 1000:
                    episodes.add(episode)

        if not episodes:
            return False
        floor = max(episodes)
        if floor <= current_total:
            return False

        try:
            start = max(1, _safe_int_v1105(getattr(subscribe, "start_episode", 0), 1))
            done = {
                _safe_int_v1105(value, 0)
                for value in (getattr(subscribe, "note", None) or [])
                if _safe_int_v1105(value, 0) > 0
            }
            lack = len(set(range(start, floor + 1)) - done)
            SubscribeOper().update(sid, {"total_episode": floor, "lack_episode": lack})
            setattr(subscribe, "total_episode", floor)
            setattr(subscribe, "lack_episode", lack)
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【分享追更】#%s %s 根据分享文件明确集号将目标总集数由 %s 向上校正为 %s，剩余 %s 集",
                sid,
                getattr(subscribe, "name", ""),
                current_total,
                floor,
                lack,
            )
            return True
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【分享追更】#%s %s 分享集数上限同步失败，继续按原目标处理：%s",
                sid,
                getattr(subscribe, "name", ""),
                str(err)[:240],
            )
            return False

    def _plan_incremental_files(
        self,
        probe: Dict[str, Any],
        assets: Dict[str, Any],
        subscribe: Any = None,
        target_path: str = "",
        stats: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        # 必须先扩目标，再交给 legacy 的 ep <= total_episode 过滤；否则新集会先被当成范围外丢弃。
        if subscribe is not None:
            self._sync_share_episode_floor_v1105(probe, subscribe)

        sanitized = dict(probe or {})
        files = list((probe or {}).get("files") or [])
        ignored: List[str] = []
        if bool(getattr(self, "_media_only", True)) and self._is_tv_subscription_v1105(subscribe):
            kept = []
            for raw in files:
                if not isinstance(raw, dict):
                    kept.append(raw)
                    continue
                path = _safe_relative_path(raw.get("relative_path") or raw.get("name") or "")
                if path and _is_video(path) and is_auxiliary_media_v1105(path):
                    ignored.append(path)
                    continue
                kept.append(raw)
            sanitized["files"] = kept

        planned = super()._plan_incremental_files(
            sanitized,
            assets,
            subscribe=subscribe,
            target_path=target_path,
            stats=stats,
        )
        if stats is not None and ignored:
            stats["ignored_auxiliary"] = len(ignored)
            stats["ignored_auxiliary_paths"] = ignored[:8]
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【文件识别】#%s %s 已忽略 %s 个非正片辅助视频：%s",
                _safe_int_v1105(getattr(subscribe, "id", 0), 0),
                getattr(subscribe, "name", "") if subscribe is not None else "",
                len(ignored),
                "、".join(ignored[:6]),
            )
        return planned

    def _entry_processed(self, entry: Dict[str, Any], subscribe: Any = None) -> bool:
        """历史去重记录必须绑定当时的追更目标；目标增长时允许重新检查。"""
        key = self._processed_entry_key(entry, subscribe)
        if not key:
            return False
        records = self.get_data("processed_entries") or {}
        raw = records.get(key) if isinstance(records, dict) else None
        if not raw:
            return False
        if subscribe is None or not self._is_tv_subscription_v1105(subscribe):
            return True

        try:
            missing = list(self._subscription_missing_episodes(subscribe) or [])
        except Exception:
            missing = []
        if not missing:
            return True

        # v1.10.4 以前记录没有目标快照。对仍缺集的订阅升级后只重新开放一次，
        # 本轮重新处理后 _mark_entry_processed 会补 target_total，之后不会反复探测。
        if not isinstance(raw, dict):
            return False
        status = str(raw.get("status") or "processed")
        if status not in _TARGET_BOUND_PROCESSED_STATES:
            return True
        current_total = max(0, _safe_int_v1105(getattr(subscribe, "total_episode", 0), 0))
        stored_total = max(0, _safe_int_v1105(raw.get("target_total"), 0))
        if stored_total <= 0:
            return False
        return current_total <= stored_total

    def _mark_entry_processed(
        self,
        entry: Dict[str, Any],
        status: str,
        message: str = "",
        subscribe: Any = None,
    ) -> None:
        super()._mark_entry_processed(entry, status, message, subscribe)
        if subscribe is None or not self._is_tv_subscription_v1105(subscribe):
            return
        key = self._processed_entry_key(entry, subscribe)
        if not key:
            return
        try:
            records = self.get_data("processed_entries") or {}
            if not isinstance(records, dict):
                return
            raw = records.get(key)
            if not isinstance(raw, dict):
                return
            raw = dict(raw)
            raw["target_total"] = max(0, _safe_int_v1105(getattr(subscribe, "total_episode", 0), 0))
            raw["target_start"] = max(1, _safe_int_v1105(getattr(subscribe, "start_episode", 0), 1))
            try:
                raw["target_missing"] = len(self._subscription_missing_episodes(subscribe) or [])
            except Exception:
                pass
            records[key] = raw
            self.save_data("processed_entries", records)
        except Exception:
            # 去重元数据增强绝不能影响真实转存结果。
            return


__all__ = [
    "GuangYaContentResilienceV1105Mixin",
    "is_auxiliary_media_v1105",
]
