"""v1.12.10 迅雷季包物理资源栅栏。

修复同一真实迅雷分享被同一剧集的多个 MoviePilot season 订阅同时消费，导致光鸭端出现
01.mp4 / 01(1).mp4 这类物理重复文件的问题。

安全原则：
1. TV 无明确季号的包若解析到超过订阅本季总集数的集号，整包拒绝，禁止先裁剪目标集再
   把其它季资源冒充当前季；
2. 无明确季号的同一迅雷 share，在同一系列内首个真实成功 season 会取得持久 claim；
   之后其它订阅/season 不得再次消费同一物理 share；同一订阅重试保持幂等；
3. 明确带 Sxx/Season/第x季 的真实多季包不使用这个 seasonless claim，由既有文件级 planner
   按显式季号拆分；
4. 同一系列的迅雷入口串行化，确保两个 season 不会同时越过 claim 门禁；
5. 只在光鸭确认某个迅雷文件真实成功后写 claim，失败候选不会永久占坑。

本层不修改 GYING 搜索、迅雷 JSON 协议、质量过滤、MoviePilot 订阅规则或来源优先级。
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .content_resilience_v1105 import is_auxiliary_media_v1105
from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _is_video
from .media_identity_v1111 import explicit_seasons_v1111


class GuangYaXunleiSeasonFenceV11210Mixin:
    """在迅雷真实文件列表与实际秒传之间增加 season/package 物理唯一性门禁。"""

    plugin_version = "1.12.10"
    build_id = "20260905-r56"
    _xunlei_season_claim_data_v11210 = "xunlei_share_season_claims_v11210"
    _xunlei_series_lock_guard_v11210 = threading.Lock()
    _xunlei_series_locks_v11210: Dict[str, threading.RLock] = {}
    _xunlei_claim_guard_v11210 = threading.RLock()

    # ------------------------------------------------------------------
    # identity / package helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_positive_int_v11210(value: Any) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    def _xunlei_series_key_v11210(self, subscribe: Any) -> str:
        """复用既有稳定 media fact 身份，仅去掉 season 后缀作为系列级互斥键。"""
        try:
            prefix = str(self._media_fact_prefix(subscribe) or "").strip()
        except Exception:
            prefix = ""
        if prefix:
            return re.sub(r":s\d+$", "", prefix, flags=re.I)
        source = str(getattr(getattr(subscribe, "media_source", None), "value", getattr(subscribe, "media_source", "")) or "").strip().lower()
        media_id = str(getattr(subscribe, "media_id", "") or "").strip()
        name = re.sub(r"\s+", "", str(getattr(subscribe, "name", "") or "").casefold())
        year = str(getattr(subscribe, "year", "") or "").strip()
        return f"{source or 'title'}:{media_id or name}:{year}" if (media_id or name) else ""

    def _xunlei_series_dispatch_lock_v11210(self, subscribe: Any) -> Optional[threading.RLock]:
        key = self._xunlei_series_key_v11210(subscribe)
        if not key:
            return None
        with self._xunlei_series_lock_guard_v11210:
            lock = self._xunlei_series_locks_v11210.get(key)
            if lock is None:
                lock = threading.RLock()
                self._xunlei_series_locks_v11210[key] = lock
            return lock

    @staticmethod
    def _xunlei_template_paths_v11210(template: Dict[str, Any]) -> List[str]:
        paths: List[str] = []
        for row in (template.get("files") or []) if isinstance(template, dict) else []:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or row.get("name") or "").replace("\\", "/").strip()
            if path:
                paths.append(path)
        return paths

    def _xunlei_video_paths_v11210(self, template: Dict[str, Any]) -> List[str]:
        return [
            path for path in self._xunlei_template_paths_v11210(template)
            if _is_video(path) and not is_auxiliary_media_v1105(path)
        ]

    def _xunlei_package_episodes_v11210(self, subscribe: Any, template: Dict[str, Any]) -> Set[int]:
        paths = self._xunlei_video_paths_v11210(template)
        if not paths:
            return set()
        season = self._safe_positive_int_v11210(getattr(subscribe, "season", 0))
        threshold = float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)
        episodes: Set[int] = set()
        for path in paths:
            try:
                result = resolve_episode(
                    path,
                    package_paths=paths,
                    season_hint=season or None,
                )
                episodes.update(int(value) for value in reliable_episode_set(result, threshold) if int(value or 0) > 0)
            except Exception:
                continue
        return episodes

    def _xunlei_package_explicit_seasons_v11210(self, template: Dict[str, Any]) -> Set[int]:
        return set(explicit_seasons_v1111(self._xunlei_template_paths_v11210(template)))

    # ------------------------------------------------------------------
    # persistent seasonless share claim
    # ------------------------------------------------------------------
    def _xunlei_claim_store_v11210(self) -> Dict[str, Any]:
        raw = self.get_data(self._xunlei_season_claim_data_v11210) or {}
        store = dict(raw) if isinstance(raw, dict) else {}
        store.setdefault("schema", 1)
        items = store.get("items")
        store["items"] = dict(items) if isinstance(items, dict) else {}
        return store

    def _xunlei_claim_key_v11210(self, subscribe: Any, share_id: str) -> str:
        return f"{self._xunlei_series_key_v11210(subscribe)}|{str(share_id or '').strip()}"

    def _xunlei_write_success_claim_v11210(
        self,
        subscribe: Any,
        share_id: str,
        path: str,
    ) -> Dict[str, Any]:
        """仅真实成功文件触发；首个 owner 永不被后来的订阅覆盖。"""
        if not subscribe or self._is_movie_subscription(subscribe):
            return {}
        share_id = str(share_id or "").strip()
        path = str(path or "").replace("\\", "/").strip()
        if not share_id or not path or explicit_seasons_v1111([path]):
            return {}
        series = self._xunlei_series_key_v11210(subscribe)
        season = self._safe_positive_int_v11210(getattr(subscribe, "season", 0))
        sid = self._safe_positive_int_v11210(getattr(subscribe, "id", 0))
        if not series or season <= 0 or sid <= 0:
            return {}
        key = f"{series}|{share_id}"
        with self._xunlei_claim_guard_v11210:
            store = self._xunlei_claim_store_v11210()
            items = store["items"]
            existing = dict(items.get(key) or {})
            if existing:
                return existing
            row = {
                "series": series,
                "share_id": share_id,
                "season": season,
                "subscribe_id": sid,
                "path": path[:500],
                "claimed_at": time.time(),
            }
            items[key] = row
            self.save_data(self._xunlei_season_claim_data_v11210, store)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【迅雷季栅栏v1.12.10】#%s S%02d 已取得无季号 share=%s 物理资源 claim",
            sid,
            season,
            share_id[:24],
        )
        return row

    def _xunlei_recover_legacy_claim_v11210(self, subscribe: Any, share_id: str) -> Dict[str, Any]:
        """兼容升级前成功状态：从 xunlei_flash_state 回推同系列 share 的首个成功 owner。"""
        series = self._xunlei_series_key_v11210(subscribe)
        share_id = str(share_id or "").strip()
        if not series or not share_id:
            return {}
        try:
            state = self._xunlei_state()
            items = list((state.get("items") or {}).values()) if isinstance(state, dict) else []
        except Exception:
            return {}
        rows = sorted(
            (row for row in items if isinstance(row, dict)),
            key=lambda row: float(row.get("updated_ts") or 0),
        )
        for row in rows:
            if str(row.get("state") or "") != "completed" or str(row.get("share_id") or "") != share_id:
                continue
            path = str(row.get("path") or "").replace("\\", "/").strip()
            if not path or explicit_seasons_v1111([path]):
                continue
            sid = self._safe_positive_int_v11210(row.get("subscribe_id"))
            if sid <= 0:
                continue
            try:
                owner = self._find_subscription(sid)
            except Exception:
                owner = None
            if not owner or self._xunlei_series_key_v11210(owner) != series:
                continue
            return self._xunlei_write_success_claim_v11210(owner, share_id, path)
        return {}

    def _xunlei_existing_claim_v11210(self, subscribe: Any, share_id: str) -> Dict[str, Any]:
        key = self._xunlei_claim_key_v11210(subscribe, share_id)
        if not key or key.endswith("|"):
            return {}
        with self._xunlei_claim_guard_v11210:
            store = self._xunlei_claim_store_v11210()
            row = dict((store.get("items") or {}).get(key) or {})
        return row or self._xunlei_recover_legacy_claim_v11210(subscribe, share_id)

    # ------------------------------------------------------------------
    # final Xunlei identity gate
    # ------------------------------------------------------------------
    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ) -> Tuple[bool, str]:
        accepted, reason = super()._xunlei_json_identity_matches_v1123(subscribe, candidate, info, template)
        if not accepted or self._is_movie_subscription(subscribe):
            return bool(accepted), str(reason or "")

        season = self._safe_positive_int_v11210(getattr(subscribe, "season", 0))
        if season <= 0:
            return bool(accepted), str(reason or "")
        explicit_seasons = self._xunlei_package_explicit_seasons_v11210(template)

        # 显式季号由既有媒体身份 + planner 负责；真实多季包也不能被 seasonless claim 锁死。
        if explicit_seasons:
            if len(explicit_seasons) == 1 and season not in explicit_seasons:
                return False, f"迅雷资源明确季号冲突：订阅=S{season:02d} 实际={sorted(explicit_seasons)}"
            return bool(accepted), str(reason or "")

        total = self._safe_positive_int_v11210(getattr(subscribe, "total_episode", 0))
        package_episodes = self._xunlei_package_episodes_v11210(subscribe, template)
        if total > 0 and package_episodes and max(package_episodes) > total:
            actual_max = max(package_episodes)
            message = (
                f"迅雷无季号资源结构冲突：订阅 S{season:02d} 共{total}集，"
                f"但实际包解析到 E{actual_max:02d}；禁止裁剪 E01-E{total:02d} 后把其它季资源冒充本季"
            )
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷季栅栏v1.12.10】#%s %s",
                self._safe_positive_int_v11210(getattr(subscribe, "id", 0)),
                message,
            )
            return False, message

        share_id = str(
            candidate.get("share_id")
            or candidate.get("shareId")
            or template.get("shareId")
            or info.get("share_id")
            or info.get("shareId")
            or ""
        ).strip()
        if not share_id:
            return bool(accepted), str(reason or "")
        claim = self._xunlei_existing_claim_v11210(subscribe, share_id)
        if not claim:
            return bool(accepted), str(reason or "")

        sid = self._safe_positive_int_v11210(getattr(subscribe, "id", 0))
        owner_sid = self._safe_positive_int_v11210(claim.get("subscribe_id"))
        owner_season = self._safe_positive_int_v11210(claim.get("season"))
        if owner_sid == sid and sid > 0:
            return bool(accepted), str(reason or "")

        message = (
            f"同一无季号迅雷分享已由本系列 S{owner_season:02d} / 订阅#{owner_sid or '-'} 成功消费；"
            f"当前 S{season:02d} / 订阅#{sid or '-'} 禁止再次导入同一物理 share"
        )
        self._plugin_log(
            "WARNING",
            "【光鸭转存助手】【迅雷季栅栏v1.12.10】share=%s %s",
            share_id[:24],
            message,
        )
        return False, message

    # ------------------------------------------------------------------
    # success claim + concurrent series serialization
    # ------------------------------------------------------------------
    def _save_xunlei_state(self, state: Dict[str, Any]) -> None:
        super()._save_xunlei_state(state)
        items = state.get("items") if isinstance(state, dict) else None
        if not isinstance(items, dict) or not items:
            return
        completed = [
            row for row in items.values()
            if isinstance(row, dict)
            and str(row.get("state") or "") == "completed"
            and _is_video(str(row.get("path") or ""))
        ]
        if not completed:
            return
        latest = max(float(row.get("updated_ts") or 0) for row in completed)
        for row in completed:
            if float(row.get("updated_ts") or 0) < latest - 0.01:
                continue
            sid = self._safe_positive_int_v11210(row.get("subscribe_id"))
            share_id = str(row.get("share_id") or "").strip()
            path = str(row.get("path") or "").strip()
            if sid <= 0 or not share_id or not path:
                continue
            try:
                subscribe = self._find_subscription(sid)
            except Exception:
                subscribe = None
            if subscribe:
                self._xunlei_write_success_claim_v11210(subscribe, share_id, path)

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        if self._is_movie_subscription(subscribe):
            return super()._dispatch_xunlei_flash(subscribe)
        lock = self._xunlei_series_dispatch_lock_v11210(subscribe)
        if lock is None:
            return super()._dispatch_xunlei_flash(subscribe)
        with lock:
            return super()._dispatch_xunlei_flash(subscribe)


__all__ = ["GuangYaXunleiSeasonFenceV11210Mixin"]
