"""v1.12.7 搜到资源但未提交光鸭的后置门禁修复。

本层修复三类实机问题：
1. 连续剧 S02+ 的资源年份通常是“本季发行年份”，MoviePilot 订阅年份则是系列首播年份；
   当标题、季号和剧集结构都吻合时，不再把这种年份差异当作跨媒体硬冲突。
2. GYING 搜索卡片已经命中订阅，但真实迅雷分享使用合法别名时，允许在“搜索标题匹配 +
   分享顶层名与文件名内部一致 + 年/季无冲突 + 明确剧集结构”的多重证据下桥接；
   不做编辑距离模糊匹配，也不放宽电影和错误季号。
3. Magnet/ED2K 拆包进入 needs_review 后不再永久死亡：缺集/季/目标证据变化立即重评，
   证据不变最多每 6 小时复核一次，避免 10 分钟追更形成请求风暴。

同时把 planner 的 missing/reserved/target/episodes/indexes/ambiguous 打入一条可观测日志，
以后“已经找到资源但没有动作”可以直接从日志确认卡在哪一层。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from .legacy import _subscription_aliases
from .media_identity_v1111 import (
    any_alias_title_match_v1111,
    assess_media_identity_v1111,
    explicit_seasons_v1111,
    explicit_years_v1111,
    has_episode_structure_v1111,
    strong_title_match_v1111,
    title_variants_v1111,
)


class GuangYaResourceGateV1127Mixin:
    """只救回有强证据的误杀资源，不改变既有来源优先级和缺集终态栅栏。"""

    plugin_version = "1.12.7"
    build_id = "20260905-r53"
    _review_recheck_seconds_v1127 = 6 * 60 * 60

    # ------------------------------------------------------------------
    # TV 身份上下文
    # ------------------------------------------------------------------
    def _tv_identity_context_v1127(self, subscribe: Any) -> Dict[str, Any]:
        try:
            is_movie = bool(self._is_movie_subscription(subscribe))
        except Exception:
            raw = str(getattr(subscribe, "type", "") or "").lower()
            is_movie = "movie" in raw or "电影" in raw
        aliases_fn = getattr(self, "_identity_aliases_v1111", None)
        aliases = list(aliases_fn(subscribe) if callable(aliases_fn) else (_subscription_aliases(subscribe) or []))
        primary = str(getattr(subscribe, "name", "") or "").strip()
        if primary and primary not in aliases:
            aliases.insert(0, primary)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        return {
            "is_movie": is_movie,
            "aliases": [str(value or "").strip() for value in aliases if str(value or "").strip()],
            "year": str(getattr(subscribe, "year", "") or "").strip(),
            "season": season,
        }

    @staticmethod
    def _title_keys_v1127(values: Iterable[Any], *, expected_year: Any = None) -> Set[str]:
        keys: Set[str] = set()
        for value in values or []:
            keys.update(title_variants_v1111(value, expected_year=expected_year))
        return keys

    # ------------------------------------------------------------------
    # GYING 搜索候选：S02+ 允许季发行年份，不让候选在打开分享前被误杀
    # ------------------------------------------------------------------
    def _provider_candidate_matches(self, subscribe: Any, row: Dict[str, Any]) -> bool:
        if bool(super()._provider_candidate_matches(subscribe, row)):
            return True

        context = self._tv_identity_context_v1127(subscribe)
        if context["is_movie"] or int(context["season"] or 0) <= 1:
            return False
        aliases: List[str] = list(context["aliases"] or [])
        if not aliases:
            return False

        evidences = [row.get("search_title"), row.get("name"), row.get("label"), row.get("year")]
        seasons = explicit_seasons_v1111(evidences)
        expected_season = int(context["season"] or 0)
        if seasons != {expected_season}:
            return False

        years = explicit_years_v1111(evidences, aliases)
        expected_year = str(context["year"] or "")
        if not expected_year or not years or expected_year in years:
            return False

        # 用真实出现的“本季年份”仅做标题清洗重试；标题本身仍必须匹配已知订阅别名。
        for actual_year in sorted(years):
            if any(
                str(evidence or "").strip()
                and strong_title_match_v1111(alias, evidence, expected_year=actual_year)
                for alias in aliases
                for evidence in evidences
            ):
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【媒体身份v1.12.7】#%s S%02d 候选使用季发行年份 %s（系列年份 %s）通过预筛",
                    int(getattr(subscribe, "id", 0) or 0),
                    expected_season,
                    actual_year,
                    expected_year,
                )
                return True
        return False

    # ------------------------------------------------------------------
    # 迅雷最终身份门禁：多季年份桥接 + 合法别名多证据桥接
    # ------------------------------------------------------------------
    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ) -> Tuple[bool, str]:
        accepted, original_reason = super()._xunlei_json_identity_matches_v1123(
            subscribe, candidate, info, template
        )
        if accepted:
            return True, original_reason

        context = self._tv_identity_context_v1127(subscribe)
        if context["is_movie"]:
            return False, original_reason
        aliases: List[str] = list(context["aliases"] or [])
        if not aliases:
            return False, original_reason

        expected_year = str(context["year"] or "")
        expected_season = int(context["season"] or 0)
        search_title = str(candidate.get("search_title") or "").strip()
        resource_name = str(candidate.get("name") or "").strip()
        # 与 v1.11.1 保持一致：panlist 没 name 时回填的 search title 只能算 discovery 证据。
        if resource_name and search_title and resource_name.casefold() == search_title.casefold():
            resource_name = ""
        primary = [str(info.get("title") or "").strip(), resource_name]
        primary = [value for value in primary if value]
        files = [
            str(row.get("path") or row.get("name") or "").strip()
            for row in (template.get("files") or [])
            if isinstance(row, dict) and str(row.get("path") or row.get("name") or "").strip()
        ]
        discovery = [search_title, str(candidate.get("label") or "").strip()]
        discovery = [value for value in discovery if value]
        actual = [*primary, *files]

        seasons = explicit_seasons_v1111(actual)
        if expected_season > 0 and seasons and seasons != {expected_season}:
            return False, original_reason
        years = explicit_years_v1111(actual, aliases)

        # 1) 连续剧第二季及以后：资源显式写对季号时，把不同年份当作本季发行年份再评估一次。
        if (
            expected_season > 1
            and seasons == {expected_season}
            and expected_year
            and years
            and expected_year not in years
            and has_episode_structure_v1111(files)
        ):
            for actual_year in sorted(years):
                assessment = assess_media_identity_v1111(
                    aliases=aliases,
                    expected_year=actual_year,
                    expected_season=expected_season,
                    is_movie=False,
                    primary_evidences=primary,
                    file_evidences=files[:300],
                    discovery_evidences=discovery,
                    threshold=50,
                )
                if assessment.get("ok"):
                    reason = (
                        f"S{expected_season:02d} 季发行年份桥接：系列年份={expected_year}，"
                        f"资源年份={actual_year}；{assessment.get('reason') or ''}"
                    )
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【媒体身份v1.12.7】#%s %s",
                        int(getattr(subscribe, "id", 0) or 0),
                        reason,
                    )
                    return True, reason

        # 2) 合法别名桥接：搜索卡片必须命中已知订阅别名；真实顶层别名还必须与文件名内部一致。
        #    年/季若显式出现必须无冲突，并且文件必须有明确剧集结构。电影不走此桥接。
        discovery_match = any_alias_title_match_v1111(aliases, discovery, expected_year=expected_year)
        if not discovery_match or not primary or not files or not has_episode_structure_v1111(files):
            return False, original_reason
        if expected_season > 0 and seasons != {expected_season}:
            return False, original_reason

        year_compatible = not years or not expected_year or expected_year in years
        season_year_bridge = bool(
            expected_season > 1
            and seasons == {expected_season}
            and years
            and expected_year
            and expected_year not in years
        )
        if not (year_compatible or season_year_bridge):
            return False, original_reason

        strip_year = expected_year
        if season_year_bridge and years:
            strip_year = sorted(years)[0]
        primary_keys = self._title_keys_v1127(primary, expected_year=strip_year)
        file_keys = self._title_keys_v1127(files[:100], expected_year=strip_year)
        if not primary_keys.intersection(file_keys):
            return False, original_reason

        reason = (
            "合法别名桥接：GYING 发现标题命中订阅，真实分享顶层名与内部剧集文件一致，"
            f"季号=S{expected_season:02d}，年份证据={'/'.join(sorted(years)) or '缺失无冲突'}"
        )
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【媒体身份v1.12.7】#%s %s",
            int(getattr(subscribe, "id", 0) or 0),
            reason,
        )
        return True, reason

    # ------------------------------------------------------------------
    # 拆包可观测性
    # ------------------------------------------------------------------
    def _planner_file_selection(
        self,
        source: Dict[str, Any],
        subscribe: Any,
        resolve_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = dict(super()._planner_file_selection(source, subscribe, resolve_data) or {})
        try:
            if self._is_movie_subscription(subscribe):
                return result
            missing = {
                int(value) for value in (self._subscription_missing_episodes(subscribe) or [])
                if int(value or 0) > 0
            }
            reservations = dict(self._pending_reservations(subscribe) or {})
            reserved = {
                int(value) for value in (reservations.get("episodes") or set())
                if int(value or 0) > 0
            }
            configured = {
                int(value) for value in (source.get("target_episodes") or [])
                if str(value).isdigit() and int(value) > 0
            }
            target = (configured or missing).intersection(missing) - reserved
            planned = [int(value) for value in (result.get("indexes") or [])]
            resolved = [int(value) for value in (result.get("episodes") or [])]
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【拆包v1.12.7】#%s type=%s missing=%s reserved=%s target=%s resolved=%s indexes=%s ambiguous=%s message=%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(source.get("type") or "-")[:20],
                sorted(missing),
                sorted(reserved),
                sorted(target),
                sorted(resolved),
                planned,
                bool(result.get("ambiguous")),
                str(result.get("message") or "-")[:240],
            )
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # needs_review 不再永久死亡
    # ------------------------------------------------------------------
    def _review_fingerprint_v1127(self, subscribe: Any, source: Dict[str, Any]) -> str:
        try:
            missing = sorted({
                int(value) for value in (self._subscription_missing_episodes(subscribe) or [])
                if int(value or 0) > 0
            })
        except Exception:
            missing = []
        targets: List[int] = []
        for raw in source.get("target_episodes") or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in targets:
                targets.append(value)
        try:
            season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            season = 0
        try:
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            total = 0
        hint = str(source.get("episode_hint") or "").strip()
        return f"s={season}|total={total}|missing={','.join(map(str, missing))}|target={','.join(map(str, sorted(targets)))}|hint={hint}"

    def _mark_offline_failure(
        self,
        source: Dict[str, Any],
        error: Exception | str,
        *,
        attempt_increment: bool = True,
    ) -> Dict[str, Any]:
        updated = dict(super()._mark_offline_failure(
            source, error, attempt_increment=attempt_increment
        ) or source)
        if str(updated.get("state") or "") != "needs_review":
            return updated
        subscribe = self._find_subscription(int(updated.get("subscribe_id") or 0))
        if not subscribe:
            return updated
        fingerprint = self._review_fingerprint_v1127(subscribe, updated)
        return dict(self._update_source(
            str(updated.get("id") or ""),
            review_fingerprint_v1127=fingerprint,
            review_at_v1127=time.time(),
        ) or updated)

    def _existing_source(self, subscribe_id: int, source_type: str, identity: str) -> Dict[str, Any]:
        existing = dict(super()._existing_source(subscribe_id, source_type, identity) or {})
        if str(existing.get("state") or "") != "needs_review":
            return existing
        subscribe = self._find_subscription(int(subscribe_id or 0))
        if not subscribe:
            return existing

        current = self._review_fingerprint_v1127(subscribe, existing)
        previous = str(existing.get("review_fingerprint_v1127") or "")
        try:
            reviewed_at = float(existing.get("review_at_v1127") or 0)
        except (TypeError, ValueError):
            reviewed_at = 0.0
        now = time.time()
        evidence_changed = bool(previous and previous != current)
        legacy_review = not previous
        expired = bool(reviewed_at and now - reviewed_at >= int(self._review_recheck_seconds_v1127))
        if not (legacy_review or evidence_changed or expired):
            return existing

        reason = "旧版 needs_review 首次迁移复核" if legacy_review else ("缺集/季/目标证据已变化" if evidence_changed else "needs_review 已满 6 小时")
        updated = dict(self._update_source(
            str(existing.get("id") or ""),
            state="new",
            enabled=True,
            auto_dispatch=True,
            last_error="",
            next_retry_at=0,
            review_reopened_at_v1127=self._now_text(),
            review_reopen_reason_v1127=reason,
        ) or existing)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【拆包v1.12.7】来源 %s 从 needs_review 自动重新评估：%s",
            str(existing.get("id") or "-"),
            reason,
        )
        # 调度层只根据本次返回值判断“是否已有活跃候选”；用临时非活跃状态让它继续
        # 走既有 _upsert_source + _spawn_source_dispatch。持久状态已经恢复为 new。
        updated["state"] = "review_reopen"
        return updated


__all__ = ["GuangYaResourceGateV1127Mixin"]
