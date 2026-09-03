"""v1.11.1 实际资源媒体身份总门禁。"""
from __future__ import annotations

from typing import Any, Dict, List

from .legacy import _is_video, _subscription_aliases
from .media_identity_v1111 import (
    assess_media_identity_v1111,
    explicit_seasons_v1111,
    explicit_years_v1111,
    strong_title_match_v1111,
)

_AMBIGUOUS_PREFIX_V1111 = "EPISODE_AMBIGUOUS:"


class GuangYaMediaIdentityGuardV1111Mixin:
    """执行前核验真实 payload；明确冲突硬拒绝，缺字段按多证据置信度处理。"""

    plugin_version = "1.11.1"
    build_id = "20260903-r43"

    @staticmethod
    def _identity_aliases_v1111(subscribe: Any) -> List[str]:
        aliases = list(_subscription_aliases(subscribe) or [])
        primary = str(getattr(subscribe, "name", "") or "").strip()
        if primary and primary not in aliases:
            aliases.insert(0, primary)
        return aliases

    @staticmethod
    def _identity_is_movie_v1111(subscribe: Any) -> bool:
        raw = str(getattr(subscribe, "type", "") or "")
        return "movie" in raw.lower() or "电影" in raw

    def _identity_expected_season_v1111(self, subscribe: Any) -> int:
        if self._identity_is_movie_v1111(subscribe):
            return 0
        try:
            return int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _provider_candidate_matches(self, subscribe: Any, row: Dict[str, Any]) -> bool:
        """搜索阶段只做预筛；最终仍由真实迅雷 JSON / cloud resolve 结果确认。"""
        aliases = self._identity_aliases_v1111(subscribe)
        year = str(getattr(subscribe, "year", "") or "").strip()
        season = self._identity_expected_season_v1111(subscribe)
        is_movie = self._identity_is_movie_v1111(subscribe)
        title_evidence = [row.get("search_title"), row.get("name"), row.get("label")]
        if not any(
            str(evidence or "").strip()
            and strong_title_match_v1111(alias, evidence, expected_year=year)
            for alias in aliases
            for evidence in title_evidence
        ):
            return False
        raw_evidence = [*title_evidence, row.get("year")]
        years = explicit_years_v1111(raw_evidence, aliases)
        if year and years and year not in years:
            return False
        seasons = explicit_seasons_v1111(raw_evidence)
        if is_movie and seasons:
            return False
        if not is_movie and season > 0 and seasons and season not in seasons:
            return False
        return True

    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ):
        """迅雷最终门禁：实际资源为主，搜索卡片只能补充弱证据，不能覆盖硬冲突。"""
        aliases = self._identity_aliases_v1111(subscribe)
        year = str(getattr(subscribe, "year", "") or "").strip()
        season = self._identity_expected_season_v1111(subscribe)
        search_title = str(candidate.get("search_title") or "").strip()
        resource_name = str(candidate.get("name") or "").strip()
        # GYING 在 panlist 没有 name 时可能把搜索卡片 title 回填到 candidate.name；
        # 这种值降级成 discovery 弱证据，不能伪装成真实分享标题。
        if resource_name and search_title and resource_name.casefold() == search_title.casefold():
            resource_name = ""
        files = [
            str(row.get("path") or row.get("name") or "").strip()
            for row in (template.get("files") or [])
            if isinstance(row, dict) and str(row.get("path") or row.get("name") or "").strip()
        ]
        assessment = assess_media_identity_v1111(
            aliases=aliases,
            expected_year=year,
            expected_season=season,
            is_movie=self._identity_is_movie_v1111(subscribe),
            primary_evidences=[str(info.get("title") or "").strip(), resource_name],
            file_evidences=files[:300],
            discovery_evidences=[search_title, candidate.get("label")],
            threshold=50,
        )
        if not assessment.get("ok"):
            return False, f"迅雷实际资源身份拒绝：{assessment.get('reason') or '置信度不足'}"
        return True, f"迅雷媒体身份通过：score={assessment.get('score', 0)}；{assessment.get('reason') or ''}"

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        """Magnet/ED2K resolve 后用真实 btResInfo/subfiles 做最终身份确认。"""
        result = dict(super()._resolve_offline_source(source, subscribe) or {})
        data = result.get("resolve_data") if isinstance(result.get("resolve_data"), dict) else {}
        bt_info = data.get("btResInfo") if isinstance(data.get("btResInfo"), dict) else {}
        files: List[str] = []
        subfiles = bt_info.get("subfiles") if isinstance(bt_info.get("subfiles"), list) else []
        for row in subfiles[:500]:
            if not isinstance(row, dict):
                continue
            value = str(row.get("fileName") or row.get("relative_path") or row.get("name") or "").strip()
            if value:
                files.append(value)
        season = self._identity_expected_season_v1111(subscribe)
        assessment = assess_media_identity_v1111(
            aliases=self._identity_aliases_v1111(subscribe),
            expected_year=getattr(subscribe, "year", None),
            expected_season=season,
            is_movie=self._identity_is_movie_v1111(subscribe),
            primary_evidences=[
                str(result.get("resolved_name") or "").strip(),
                str(bt_info.get("fileName") or "").strip(),
            ],
            file_evidences=files,
            discovery_evidences=[
                source.get("search_title"), source.get("title"), source.get("name"), source.get("label")
            ],
            threshold=50,
        )
        if not assessment.get("ok"):
            raise RuntimeError(
                f"{_AMBIGUOUS_PREFIX_V1111}媒体身份门禁：{assessment.get('reason') or '置信度不足'}"
            )
        result["identity_score_v1111"] = int(assessment.get("score") or 0)
        result["identity_reason_v1111"] = str(assessment.get("reason") or "")
        return result

    def _plan_incremental_files(
        self,
        probe: Dict[str, Any],
        assets: Dict[str, Any],
        subscribe: Any = None,
        target_path: str = "",
        stats: Dict[str, Any] | None = None,
    ):
        """直接分享先处理硬冲突；缺少年份/季号不会因为信息不足直接拒绝。"""
        if subscribe is not None:
            paths = [
                str(row.get("relative_path") or row.get("name") or "").strip()
                for row in (probe.get("files") or [])
                if isinstance(row, dict)
                and _is_video(str(row.get("relative_path") or row.get("name") or ""))
            ]
            if paths:
                aliases = self._identity_aliases_v1111(subscribe)
                year = str(getattr(subscribe, "year", "") or "").strip()
                years = explicit_years_v1111(paths, aliases)
                season = self._identity_expected_season_v1111(subscribe)
                seasons = explicit_seasons_v1111(paths)
                if year and years and year not in years:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【媒体身份】直接分享年份冲突，拒绝规划：期望=%s 实际=%s",
                        year,
                        sorted(years),
                    )
                    return []
                if self._identity_is_movie_v1111(subscribe) and seasons:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【媒体身份】电影直接分享出现季号 %s，拒绝规划",
                        sorted(seasons),
                    )
                    return []
                if not self._identity_is_movie_v1111(subscribe) and season > 0 and seasons and season not in seasons:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【媒体身份】直接分享季号冲突，期望=S%02d 实际=%s，拒绝规划",
                        season,
                        sorted(seasons),
                    )
                    return []
        return super()._plan_incremental_files(
            probe,
            assets,
            subscribe=subscribe,
            target_path=target_path,
            stats=stats,
        )


__all__ = ["GuangYaMediaIdentityGuardV1111Mixin"]
