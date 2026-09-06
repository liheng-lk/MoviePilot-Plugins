"""v1.12.18 候选排序与频道来源质量学习。

本层只改变“同阶段候选的尝试顺序”，绝不改变来源优先级或最终写盘门禁：
- 迅雷仍先于其它来源；光鸭直接转存仍先于 Magnet，Magnet 仍先于 ED2K；
- 频道/观影候选仍必须先通过 v1.12.17 discovery matcher；
- 真正写盘继续由 v1.12.13~v1.12.16 的真实 payload、年份、季、library missing、
  reservation/source claim 与不可分割物理文件栅栏裁决。

排序信号全部可解释：
1. canonical identity / 结构化标题分是主信号；
2. TV 明确覆盖当前缺集且夹带额外集更少的候选优先；
3. 迅雷候选提取码完整时只作为很小的同分信号；
4. Telegram 来源质量只从 SourceStore 的真实 completed / failed / needs_review 终态派生，
   queued/waiting/new 不参与统计；采用 Beta 先验 + 样本权重，少量样本不会形成永久霸榜。

频道质量不另建不可恢复数据库：缓存失效后可直接从现有 subscription_sources 重建。
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Iterable, List, Set, Tuple

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin


_TERMINAL_FAILURE_STATES_V11218 = {"failed", "needs_review"}
_SOURCE_QUALITY_CACHE_SECONDS_V11218 = 60.0


def _quality_key_v11218(value: Any) -> str:
    """频道质量键只保留可展示 label 的稳定字符，不保存 URL/密钥。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())[:160]


def _bayes_quality_bonus_v11218(success: int, failure: int) -> Tuple[int, float]:
    """Beta(2,2) 平滑 + 样本权重；输出最多 ±18 分的轻量排序 bonus。"""
    success = max(0, int(success or 0))
    failure = max(0, int(failure or 0))
    total = success + failure
    posterior = (success + 2.0) / (total + 4.0)
    weight = min(1.0, total / 6.0)
    bonus = int(round((posterior - 0.5) * 72.0 * weight))
    return max(-18, min(18, bonus)), posterior


class GuangYaCandidateRankingV11218Mixin(GuangYaSearchRecallV11217Mixin):
    """在 v1.12.17 宽召回之后进行保守、可解释的候选排序。"""

    plugin_version = "1.12.18"
    build_id = "20260906-r65-preview"
    _candidate_rank_log_interval_v11218 = 5 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._quality_cache_lock_v11218 = threading.RLock()
        self._quality_cache_v11218: Dict[str, Any] = {}
        self._candidate_rank_log_at_v11218: Dict[int, float] = {}
        return super().init_plugin(config)

    # ------------------------------------------------------------------
    # Channel source quality: derived only from real SourceStore terminal states
    # ------------------------------------------------------------------
    def _channel_quality_snapshot_v11218(self) -> Dict[str, Dict[str, Any]]:
        try:
            store = dict(self._source_store() or {})
        except Exception:
            store = {"items": {}, "updated_at": ""}
        signature = str(store.get("updated_at") or "")
        now = time.time()
        lock = getattr(self, "_quality_cache_lock_v11218", None)
        if lock is None:
            lock = threading.RLock()
            self._quality_cache_lock_v11218 = lock
        cache = getattr(self, "_quality_cache_v11218", None)
        if not isinstance(cache, dict):
            cache = {}
            self._quality_cache_v11218 = cache
        with lock:
            if (
                cache.get("signature") == signature
                and now - float(cache.get("at") or 0) < _SOURCE_QUALITY_CACHE_SECONDS_V11218
            ):
                return {key: dict(value) for key, value in dict(cache.get("rows") or {}).items()}

        counters: Dict[str, Dict[str, int]] = {}
        for raw in dict(store.get("items") or {}).values():
            if not isinstance(raw, dict) or str(raw.get("origin") or "") != "telegram":
                continue
            key = _quality_key_v11218(raw.get("source_label"))
            if not key:
                continue
            state = str(raw.get("state") or "").strip().lower()
            if state != "completed" and state not in _TERMINAL_FAILURE_STATES_V11218:
                continue
            row = counters.setdefault(key, {"success": 0, "failure": 0})
            if state == "completed":
                row["success"] += 1
            else:
                row["failure"] += 1

        result: Dict[str, Dict[str, Any]] = {}
        for key, row in counters.items():
            bonus, posterior = _bayes_quality_bonus_v11218(row["success"], row["failure"])
            result[key] = {
                "success": int(row["success"]),
                "failure": int(row["failure"]),
                "samples": int(row["success"] + row["failure"]),
                "posterior": round(float(posterior), 4),
                "bonus": int(bonus),
            }
        with lock:
            self._quality_cache_v11218 = {"signature": signature, "at": now, "rows": result}
        return {key: dict(value) for key, value in result.items()}

    def _channel_quality_for_entry_v11218(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        key = _quality_key_v11218((entry or {}).get("source_label"))
        if not key:
            return {"success": 0, "failure": 0, "samples": 0, "posterior": 0.5, "bonus": 0}
        return dict(self._channel_quality_snapshot_v11218().get(key) or {
            "success": 0, "failure": 0, "samples": 0, "posterior": 0.5, "bonus": 0,
        })

    # ------------------------------------------------------------------
    # Shared episode specificity helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _episode_set_v11218(subscribe: Any, row: Dict[str, Any]) -> Set[int]:
        label = " ".join(
            str(value or "").strip()
            for value in (
                (row or {}).get("name"),
                (row or {}).get("search_title"),
                (row or {}).get("display_title_raw_v11217"),
                (row or {}).get("episode_hint"),
            )
            if str(value or "").strip()
        )
        if not label:
            return set()
        try:
            parsed = resolve_episode(label, season_hint=getattr(subscribe, "season", None))
            return set(reliable_episode_set(parsed, AUTO_SELECT_CONFIDENCE))
        except Exception:
            return set()

    def _missing_set_v11218(self, subscribe: Any) -> Set[int]:
        if self._is_movie_subscription(subscribe):
            return set()
        try:
            return {
                int(value) for value in (self._subscription_missing_episodes(subscribe) or [])
                if int(value or 0) > 0
            }
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # Channel entry ranking
    # ------------------------------------------------------------------
    def _channel_entry_score_v11218(self, subscribe: Any, entry: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(entry or {})
        match_score = int(row.get("match_score_v11217") or 0)
        if match_score <= 0:
            try:
                matched, detail = self._structured_candidate_match_v11217(subscribe, row)
                if matched:
                    match_score = int(detail.get("score") or 0)
            except Exception:
                match_score = 0
        # 已由旧 exact matcher 命中的候选即使没有 v1.12.17 标记，也保持中高基线；
        # 质量学习不能把未知身份候选抬到 canonical 候选之上。
        if match_score <= 0:
            match_score = 75

        missing = self._missing_set_v11218(subscribe)
        episodes = self._episode_set_v11218(subscribe, row)
        episode_bonus = 0
        overlap: Set[int] = set()
        spillover: Set[int] = set()
        if missing and episodes:
            overlap = episodes.intersection(missing)
            spillover = episodes - missing
            if overlap:
                episode_bonus = 18 + min(8, len(overlap) * 2) - min(10, len(spillover))
            else:
                episode_bonus = -30

        quality = self._channel_quality_for_entry_v11218(row)
        quality_bonus = int(quality.get("bonus") or 0)
        verified_bonus = 5 if bool(row.get("identity_verified_v11217")) else 0
        total = match_score * 10 + episode_bonus + quality_bonus + verified_bonus
        seen_at = float(row.get("cache_seen_at") or row.get("cache_added_at") or 0)
        return {
            "total": int(total),
            "identity": int(match_score),
            "episode_bonus": int(episode_bonus),
            "quality_bonus": int(quality_bonus),
            "quality_samples": int(quality.get("samples") or 0),
            "quality_success": int(quality.get("success") or 0),
            "quality_failure": int(quality.get("failure") or 0),
            "overlap": sorted(overlap),
            "spillover": sorted(spillover),
            "seen_at": seen_at,
        }

    def _channel_entry_priority_v11218(self, subscribe: Any, entry: Dict[str, Any]) -> Tuple[int, float, str]:
        detail = self._channel_entry_score_v11218(subscribe, entry)
        stable = str((entry or {}).get("message_id") or (entry or {}).get("resource_group_id") or "")
        return -int(detail["total"]), -float(detail["seen_at"]), stable

    def _maybe_log_channel_ranking_v11218(self, subscribe: Any, pairs: Iterable[Tuple[Dict[str, Any], str]]) -> None:
        rows = list(pairs or [])
        if len(rows) < 2:
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        now = time.time()
        log_state = getattr(self, "_candidate_rank_log_at_v11218", None)
        if not isinstance(log_state, dict):
            log_state = {}
            self._candidate_rank_log_at_v11218 = log_state
        last = float(log_state.get(sid, 0) or 0)
        if last and now - last < self._candidate_rank_log_interval_v11218:
            return
        log_state[sid] = now
        summary = []
        for entry, _reason in rows[:3]:
            detail = self._channel_entry_score_v11218(subscribe, entry)
            summary.append(
                "%s(score=%s,id=%s,ep=%s,q=%s/%s)" % (
                    str((entry or {}).get("source_label") or "频道")[:32],
                    detail["total"],
                    detail["identity"],
                    detail["episode_bonus"],
                    detail["quality_success"],
                    detail["quality_failure"],
                )
            )
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【候选排序v1.12.18】#%s %s 频道候选=%s；top=%s",
            sid,
            str(getattr(subscribe, "name", "") or "")[:80],
            len(rows),
            " > ".join(summary),
        )

    def _cached_matches_for_subscription(self, subscribe: Any):
        pairs = list(super()._cached_matches_for_subscription(subscribe) or [])
        ranked: List[Tuple[Dict[str, Any], str]] = []
        for entry, reason in pairs:
            row = dict(entry or {})
            detail = self._channel_entry_score_v11218(subscribe, row)
            row["rank_score_v11218"] = int(detail["total"])
            row["source_quality_bonus_v11218"] = int(detail["quality_bonus"])
            row["source_quality_samples_v11218"] = int(detail["quality_samples"])
            ranked.append((row, reason))
        ranked.sort(key=lambda pair: self._channel_entry_priority_v11218(subscribe, pair[0]))
        self._maybe_log_channel_ranking_v11218(subscribe, ranked)
        return ranked

    # ------------------------------------------------------------------
    # Xunlei candidate ranking: exact missing coverage first, then identity evidence.
    # ------------------------------------------------------------------
    def _xunlei_candidate_priority_v1125(
        self,
        subscribe: Any,
        row: Dict[str, Any],
        missing: Set[int],
    ) -> Tuple[int, int, int, int, int, int]:
        try:
            base = tuple(super()._xunlei_candidate_priority_v1125(subscribe, row, missing) or (0, 0))
        except Exception:
            base = (0, 0)
        bucket = int(base[0] if len(base) > 0 else 0)
        base_episode = int(base[1] if len(base) > 1 else 0)
        episodes = self._episode_set_v11218(subscribe, row)
        overlap = episodes.intersection(set(missing or set())) if missing else set()
        spillover = episodes - set(missing or set()) if missing else set()

        identity_score = 0
        try:
            matched, detail = self._structured_candidate_match_v11217(subscribe, dict(row or {}))
            if matched:
                identity_score = int(detail.get("score") or 0)
        except Exception:
            identity_score = 0
        passcode = 1 if str((row or {}).get("passcode") or "").strip() else 0
        return (
            bucket,
            len(spillover),
            -len(overlap),
            -identity_score,
            -passcode,
            base_episode,
        )

    def _search_viewing_xunlei(self, keyword: str):
        candidates, state = super()._search_viewing_xunlei(keyword)
        rows = [dict(row) for row in (candidates or []) if isinstance(row, dict)]
        context = getattr(self, "_gying_xunlei_context_v1125", None)
        subscribe = getattr(context, "subscribe", None) if context is not None else None
        if subscribe is not None and len(rows) > 1:
            missing = self._missing_set_v11218(subscribe)
            rows.sort(key=lambda row: self._xunlei_candidate_priority_v1125(subscribe, row, missing))
            state = dict(state or {})
            state["candidate_ranking_v11218"] = True
            state["ranked_candidates_v11218"] = len(rows)
            top = []
            for row in rows[:3]:
                top.append(
                    "%s:%s" % (
                        str(row.get("name") or row.get("search_title") or "资源")[:60],
                        self._xunlei_candidate_priority_v1125(subscribe, row, missing)[:5],
                    )
                )
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【候选排序v1.12.18】#%s %s 迅雷候选=%s；top=%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or "")[:80],
                len(rows),
                " > ".join(top),
            )
        return rows, state


__all__ = [
    "GuangYaCandidateRankingV11218Mixin",
    "_bayes_quality_bonus_v11218",
    "_quality_key_v11218",
]
