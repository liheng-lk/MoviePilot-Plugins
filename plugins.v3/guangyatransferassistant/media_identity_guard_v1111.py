"""v1.11.1 实际资源媒体身份总门禁。"""
from __future__ import annotations

from typing import Any, Dict, List

from .legacy import _is_video, _subscription_aliases
from .media_identity_v1111 import (
    explicit_seasons_v1111,
    explicit_years_v1111,
    strong_title_match_v1111,
    validate_media_evidence_v1111,
)

_AMBIGUOUS_PREFIX_V1111 = "EPISODE_AMBIGUOUS:"


class GuangYaMediaIdentityGuardV1111Mixin:
    """所有自动来源在真正执行前重新核验实际 payload，而不是信任搜索卡片。"""

    plugin_version = "1.11.1"
    build_id = "20260903-r42"

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
        """搜索阶段保守预筛；最终身份仍在迅雷 JSON / cloud resolve 后确认。"""
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
        """迅雷最终门禁只信分享真实标题/JSON 路径，搜索卡片绝不能兜底。"""
        aliases = self._identity_aliases_v1111(subscribe)
        year = str(getattr(subscribe, "year", "") or "").strip()
        season = self._identity_expected_season_v1111(subscribe)
        search_title = str(candidate.get("search_title") or "").strip()
        resource_name = str(candidate.get("name") or "").strip()
        # GYING 在 panlist 没有 name 时会把搜索卡片 title 回填到 candidate.name；
        # 这种值仍只是发现证据，不能参与最终确认。
        if resource_name and search_title and resource_name.casefold() == search_title.casefold():
            resource_name = ""
        files = [
            str(row.get("path") or row.get("name") or "").strip()
            for row in (template.get("files") or [])
            if isinstance(row, dict) and str(row.get("path") or row.get("name") or "").strip()
        ]
        actual = [str(info.get("title") or "").strip(), resource_name, *files[:300]]
        ok, reason = validate_media_evidence_v1111(
            aliases=aliases,
            expected_year=year,
            expected_season=season,
            is_movie=self._identity_is_movie_v1111(subscribe),
            evidences=actual,
            require_title=True,
            require_explicit_season=(season > 1),
        )
        if not ok:
            return False, f"迅雷实际资源身份拒绝：{reason}"
        return True, "迅雷实际 JSON 标题/年份/季号强校验通过"

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        """Magnet/ED2K 解析后使用真实 btResInfo/subfiles 做最终身份确认。"""
        result = dict(super()._resolve_offline_source(source, subscribe) or {})
        data = result.get("resolve_data") if isinstance(result.get("resolve_data"), dict) else {}
        bt_info = data.get("btResInfo") if isinstance(data.get("btResInfo"), dict) else {}
        evidences: List[str] = [
            str(result.get("resolved_name") or "").strip(),
            str(bt_info.get("fileName") or "").strip(),
        ]
        subfiles = bt_info.get("subfiles") if isinstance(bt_info.get("subfiles"), list) else []
        for row in subfiles[:500]:
            if not isinstance(row, dict):
                continue
            value = str(row.get("fileName") or row.get("relative_path") or row.get("name") or "").strip()
            if value:
                evidences.append(value)
        season = self._identity_expected_season_v1111(subscribe)
        ok, reason = validate_media_evidence_v1111(
            aliases=self._identity_aliases_v1111(subscribe),
            expected_year=getattr(subscribe, "year", None),
            expected_season=season,
            is_movie=self._identity_is_movie_v1111(subscribe),
            evidences=evidences,
            require_title=True,
            require_explicit_season=(season > 1),
        )
        if not ok:
            raise RuntimeError(f"{_AMBIGUOUS_PREFIX_V1111}媒体身份门禁：{reason}")
        return result

    def _plan_incremental_files(
        self,
        probe: Dict[str, Any],
        assets: Dict[str, Any],
        subscribe: Any = None,
        target_path: str = "",
        stats: Dict[str, Any] | None = None,
    ):
        """直接分享在抬高集数和规划文件之前先拒绝明确的年份/季号冲突。"""
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
