"""v1.12.19 高质量媒体匹配与强 claim 语义。

这一层只做两件事：
1. 电影：真正执行前必须从真实分享/resolve 结果中得到可验证的视频与作品标题证据；
2. 剧集/动漫：把“想补哪些集”与“真实解析后确认哪些集”彻底分开，只有已经
   resolve 并准备/已经提交给光鸭的物理集，才形成跨来源强 claim。

兼容原则：
- target_episodes 继续保留，作为旧 UI / 持久化兼容字段，但只表示 requested intent；
- requested_episodes 表示本次希望补的集；
- candidate_episodes 仅表示搜索标题/帖子中可高置信推断出的候选集；
- resolved_episodes 表示真实 payload 中确认的集；
- transfer_episodes 表示最终允许提交给光鸭的物理集；
- 老版本已经存在 taskId 但没有新字段时，submitted/queued/waiting/completed 仍可回退
  target_episodes 形成 claim，避免升级后把既有远端任务误当成不存在。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Set, Tuple

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _is_video
from .media_identity_v1111 import assess_media_identity_v1111


_STRONG_SOURCE_STATES_V11219 = {"submitted", "queued", "waiting", "completed"}
_ACTIVE_SOURCE_STATES_V11219 = {
    "new", "retry", "dispatching", "submitted", "queued", "waiting", "completed"
}


def _positive_episode_set_v11219(values: Iterable[Any]) -> Set[int]:
    result: Set[int] = set()
    for raw in values or []:
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            result.add(value)
    return result


def source_claim_episodes_v11219(source: Dict[str, Any]) -> Set[int]:
    """只返回已经具备强执行事实的集数；new/retry 的意图绝不占坑。"""
    row = dict(source or {})
    state = str(row.get("state") or "new").strip().lower()
    verified = _positive_episode_set_v11219(row.get("transfer_episodes") or [])
    if not verified:
        verified = _positive_episode_set_v11219(row.get("resolved_episodes") or [])

    if state in _STRONG_SOURCE_STATES_V11219:
        if verified:
            return verified
        # 升级兼容：旧版本 task 已经真实存在但没有 resolved/transfer 字段。
        if str(row.get("task_id") or "").strip():
            return _positive_episode_set_v11219(row.get("target_episodes") or [])
        return set()

    # dispatching 只有已经通过真实 payload 验证时才允许成为强 claim。
    if state == "dispatching" and bool(row.get("media_match_verified_v11219")):
        return verified
    return set()


def movie_actual_match_v11219(
    *,
    aliases: Iterable[str],
    expected_year: Any,
    primary_evidences: Iterable[Any],
    file_evidences: Iterable[Any],
) -> Dict[str, Any]:
    """电影最终身份只看真实 payload，不允许 discovery 单独把资源救回来。"""
    alias_rows = [str(value or "").strip() for value in aliases or [] if str(value or "").strip()]
    primary = [str(value or "").strip() for value in primary_evidences or [] if str(value or "").strip()]
    files = [str(value or "").strip() for value in file_evidences or [] if str(value or "").strip()]
    assessment = assess_media_identity_v1111(
        aliases=alias_rows,
        expected_year=expected_year,
        expected_season=0,
        is_movie=True,
        primary_evidences=primary,
        file_evidences=files,
        discovery_evidences=(),
        threshold=45,
    )
    actual_title_match = bool(assessment.get("primary_match") or assessment.get("file_match"))
    if not bool(assessment.get("ok")) or not actual_title_match:
        reason = str(assessment.get("reason") or "真实电影身份不足")
        if bool(assessment.get("ok")) and not actual_title_match:
            reason = "真实 payload 没有命中任何 MoviePilot/TMDB 官方标题别名"
        return {
            **dict(assessment),
            "ok": False,
            "actual_title_match": actual_title_match,
            "reason": reason,
        }
    return {
        **dict(assessment),
        "ok": True,
        "actual_title_match": True,
    }


class GuangYaMediaMatchV11219Mixin:
    """电影作品身份 + 剧集物理集两条最终匹配链的共同收口。"""

    match_schema_v11219 = 1
    _completed_claim_grace_seconds_v11219 = 15 * 60

    def _candidate_episode_set_v11219(
        self,
        subscribe: Any,
        *,
        label: str = "",
        episode_hint: str = "",
    ) -> Set[int]:
        if subscribe is None or self._is_movie_subscription(subscribe):
            return set()
        paths = [value for value in (str(label or "").strip(), str(episode_hint or "").strip()) if value]
        result: Set[int] = set()
        threshold = float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)
        for value in paths:
            try:
                parsed = resolve_episode(
                    value,
                    package_paths=paths,
                    season_hint=getattr(subscribe, "season", None),
                    episode_hint=str(episode_hint or ""),
                )
                result.update(reliable_episode_set(parsed, threshold))
            except Exception:
                continue
        return result

    def _upsert_source(self, *args: Any, **kwargs: Any):
        """保存 requested/candidate intent；不把它们提升成已验证 claim。"""
        row = dict(super()._upsert_source(*args, **kwargs) or {})
        if not row:
            return row

        subscribe_id = int(row.get("subscribe_id") or (args[0] if args else kwargs.get("subscribe_id") or 0) or 0)
        subscribe = self._find_subscription(subscribe_id) if subscribe_id else None
        is_movie = bool(subscribe is not None and self._is_movie_subscription(subscribe))
        requested = set()
        if not is_movie:
            requested = _positive_episode_set_v11219(
                kwargs.get("target_episodes")
                if "target_episodes" in kwargs
                else row.get("requested_episodes") or row.get("target_episodes") or []
            )
        candidate = self._candidate_episode_set_v11219(
            subscribe,
            label=str(kwargs.get("label") or row.get("label") or row.get("name") or ""),
            episode_hint=str(kwargs.get("episode_hint") or row.get("episode_hint") or ""),
        )

        fields: Dict[str, Any] = {
            "match_schema_v11219": int(self.match_schema_v11219),
            "media_scope_v11219": "movie" if is_movie else "series",
            "requested_episodes": sorted(requested),
            "candidate_episodes": sorted(candidate),
        }
        if "media_match_verified_v11219" not in row:
            fields["media_match_verified_v11219"] = False
        updated = self._update_source(str(row.get("id") or ""), **fields)
        return dict(updated or row)

    def _active_source_claims(self, subscribe_id: int) -> Set[int]:
        return self._effective_source_claims_v11222(subscribe_id)

    def _effective_source_claims_v11222(self, subscribe_id: int, current_source_id: str = "") -> Set[int]:
        """Planning and final payload checks must use the same claim lifetime."""
        claims: Set[int] = set()
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid) if sid else None
        missing_now: Set[int] = set()
        if subscribe is not None and not self._is_movie_subscription(subscribe):
            for raw in (self._subscription_missing_episodes(subscribe) or []):
                try:
                    value = int(raw or 0)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    missing_now.add(value)
        try:
            items = (self._source_store().get("items") or {}).values()
        except Exception:
            return claims
        for row in items:
            if not isinstance(row, dict) or int(row.get("subscribe_id") or 0) != sid:
                continue
            if current_source_id and str(row.get("id") or "") == str(current_source_id):
                continue
            if not bool(row.get("enabled", True)):
                continue
            row_claims = source_claim_episodes_v11219(row)
            if not row_claims:
                continue
            state = str(row.get("state") or "").strip().lower()
            overlap = row_claims.intersection(missing_now)
            if state == "completed" and overlap:
                try:
                    completed_ts = float(row.get("completed_ts") or 0)
                except (TypeError, ValueError):
                    completed_ts = 0.0
                grace = max(60, int(getattr(self, "_completed_claim_grace_seconds_v11219", 15 * 60) or 15 * 60))
                if completed_ts <= 0:
                    try:
                        self._plugin_log(
                            "INFO",
                            "【光鸭转存助手】【来源Claim】#%s 释放无 completed_ts 的 completed 占坑：source=%s episodes=%s",
                            sid,
                            str(row.get("id") or "-")[:60],
                            sorted(overlap),
                        )
                    except Exception:
                        pass
                    row_claims = row_claims - overlap
                    if not row_claims:
                        continue
                if completed_ts > 0 and time.time() - completed_ts >= grace:
                    try:
                        self._plugin_log(
                            "INFO",
                            "【光鸭转存助手】【来源Claim】#%s 释放过期 completed 占坑：source=%s episodes=%s age=%ss",
                            sid,
                            str(row.get("id") or "-")[:60],
                            sorted(overlap),
                            int(time.time() - completed_ts),
                        )
                    except Exception:
                        pass
                    row_claims = row_claims - overlap
                    if not row_claims:
                        continue
            claims.update(row_claims)
        return claims

    def _other_source_claims_v11214(self, subscribe_id: int, current_source_id: str = "") -> Set[int]:
        return self._effective_source_claims_v11222(subscribe_id, current_source_id)

    @staticmethod
    def _source_episode_targets_v1124(source: Dict[str, Any]) -> Set[int]:
        """EpisodeFence 只对真实提交集做取消/裁剪；未验证 intent 不再形成跨来源终止事实。"""
        return source_claim_episodes_v11219(source)

    def _movie_actual_gate_v11219(
        self,
        subscribe: Any,
        *,
        primary: Iterable[Any],
        files: Iterable[Any],
        origin: str,
    ) -> Dict[str, Any]:
        aliases_fn = getattr(self, "_identity_aliases_v1111", None)
        aliases = list(aliases_fn(subscribe) if callable(aliases_fn) else [str(getattr(subscribe, "name", "") or "")])
        assessment = movie_actual_match_v11219(
            aliases=aliases,
            expected_year=getattr(subscribe, "year", None),
            primary_evidences=primary,
            file_evidences=files,
        )
        if not bool(assessment.get("ok")):
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【电影最终匹配v1.12.19】#%s %s origin=%s 拒绝：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(origin or "-")[:40],
                str(assessment.get("reason") or "")[:320],
            )
        return assessment

    def _plan_incremental_files(
        self,
        probe: Dict[str, Any],
        assets: Dict[str, Any],
        subscribe: Any = None,
        target_path: str = "",
        stats: Dict[str, Any] | None = None,
    ):
        planned = list(super()._plan_incremental_files(
            probe,
            assets,
            subscribe=subscribe,
            target_path=target_path,
            stats=stats,
        ) or [])
        if not planned or subscribe is None or not self._is_movie_subscription(subscribe):
            return planned

        video_paths = [
            str(row.get("relative_path") or row.get("name") or "").strip()
            for row in (probe.get("files") or [])
            if isinstance(row, dict)
            and _is_video(str(row.get("relative_path") or row.get("name") or ""))
        ]
        if not video_paths:
            return []
        roots_fn = getattr(self, "_direct_share_primary_roots_v11214", None)
        primary: List[str] = []
        if callable(roots_fn):
            try:
                primary = list(roots_fn(video_paths, getattr(subscribe, "year", None)) or [])
            except Exception:
                primary = []
        assessment = self._movie_actual_gate_v11219(
            subscribe,
            primary=primary,
            files=video_paths,
            origin="guangya_share",
        )
        if not bool(assessment.get("ok")):
            if stats is not None:
                stats["movie_actual_reject_v11219"] = 1
            return []
        return planned

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        result = dict(super()._resolve_offline_source(source, subscribe) or {})
        source_id = str(source.get("id") or "")
        resolve_data = result.get("resolve_data") if isinstance(result.get("resolve_data"), dict) else {}
        bt_info = resolve_data.get("btResInfo") if isinstance(resolve_data.get("btResInfo"), dict) else {}
        subfiles = bt_info.get("subfiles") if isinstance(bt_info.get("subfiles"), list) else []

        if self._is_movie_subscription(subscribe):
            video_files = []
            for row in subfiles:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("fileName") or row.get("name") or "").strip()
                if name and _is_video(name):
                    video_files.append(name)
            resolved_name = str(result.get("resolved_name") or bt_info.get("fileName") or "").strip()
            if not video_files and resolved_name and _is_video(resolved_name):
                video_files.append(resolved_name)
            if not video_files:
                raise RuntimeError("EPISODE_AMBIGUOUS:电影真实 payload 未发现可验证的视频文件")

            assessment = self._movie_actual_gate_v11219(
                subscribe,
                primary=[resolved_name, str(bt_info.get("fileName") or "").strip()],
                files=video_files,
                origin=str(source.get("type") or "offline"),
            )
            if not bool(assessment.get("ok")):
                raise RuntimeError(
                    "EPISODE_AMBIGUOUS:电影真实资源身份拒绝："
                    + str(assessment.get("reason") or "置信度不足")[:320]
                )
            if source_id:
                self._update_source(
                    source_id,
                    media_match_verified_v11219=True,
                    media_match_score_v11219=int(assessment.get("score") or 0),
                    media_match_reason_v11219=str(assessment.get("reason") or "")[:320],
                    requested_episodes=[],
                    candidate_episodes=[],
                    resolved_episodes=[],
                    transfer_episodes=[],
                )
            result["media_match_verified_v11219"] = True
            result["media_match_score_v11219"] = int(assessment.get("score") or 0)
            return result

        physical = _positive_episode_set_v11219(result.get("physical_episodes_v11214") or [])
        latest: Dict[str, Any] = {}
        if source_id:
            try:
                latest = dict((self._source_store().get("items") or {}).get(source_id) or {})
            except Exception:
                latest = {}
        if not physical:
            physical = _positive_episode_set_v11219(latest.get("resolved_episodes") or [])
        if not physical:
            raise RuntimeError("EPISODE_AMBIGUOUS:真实资源已解析，但无法确认任何可转存剧集")

        allowed_fn = getattr(self, "_authoritative_missing_v11214", None)
        if callable(allowed_fn):
            allowed = set(allowed_fn(subscribe, current_source_id=source_id) or set())
            if not physical.issubset(allowed):
                raise RuntimeError(
                    "EPISODE_AMBIGUOUS:最终物理集超出 MoviePilot 当前真实缺集："
                    f"physical={sorted(physical)} allowed={sorted(allowed)}"
                )

        requested = _positive_episode_set_v11219(
            latest.get("requested_episodes")
            or source.get("requested_episodes")
            or source.get("target_episodes")
            or []
        )
        candidate = _positive_episode_set_v11219(
            latest.get("candidate_episodes") or source.get("candidate_episodes") or []
        )
        if source_id:
            self._update_source(
                source_id,
                media_match_verified_v11219=True,
                media_match_score_v11219=int(result.get("identity_score_v1111") or 0),
                media_match_reason_v11219=str(result.get("identity_reason_v1111") or "真实媒体身份与物理集均已通过")[:320],
                requested_episodes=sorted(requested),
                candidate_episodes=sorted(candidate),
                resolved_episodes=sorted(physical),
                transfer_episodes=sorted(physical),
            )
        result["transfer_episodes_v11219"] = sorted(physical)
        result["media_match_verified_v11219"] = True
        return result

    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """迅雷电影最终执行前按真实分享标题与视频路径再次验真。"""
        accepted, reason = super()._xunlei_json_identity_matches_v1123(
            subscribe,
            candidate,
            info,
            template,
        )
        if not accepted or not self._is_movie_subscription(subscribe):
            return bool(accepted), str(reason or "")

        search_title = str(candidate.get("search_title") or "").strip()
        resource_name = str(candidate.get("name") or "").strip()
        # panlist 缺 name 时会把 search_title 回填到 candidate.name；它仍只是 discovery。
        if resource_name and search_title and resource_name.casefold() == search_title.casefold():
            resource_name = ""

        video_files = [
            str(row.get("path") or row.get("name") or "").strip()
            for row in (template.get("files") or [])
            if isinstance(row, dict)
            and _is_video(str(row.get("path") or row.get("name") or ""))
        ]
        if not video_files:
            return False, "迅雷电影真实 payload 未发现可验证的视频文件"

        aliases_fn = getattr(self, "_identity_aliases_v1111", None)
        aliases = list(
            aliases_fn(subscribe)
            if callable(aliases_fn)
            else [str(getattr(subscribe, "name", "") or "")]
        )
        primary = [
            str(info.get("title") or "").strip(),
            resource_name,
        ]
        assessment = movie_actual_match_v11219(
            aliases=aliases,
            expected_year=getattr(subscribe, "year", None),
            primary_evidences=primary,
            file_evidences=video_files,
        )
        if bool(assessment.get("ok")):
            return True, (
                "迅雷电影真实 payload 通过："
                + str(assessment.get("reason") or f"score={assessment.get('score', 0)}")[:300]
            )

        # 保留 v1.12.16 已证明安全的严格双语真实资源桥；不做其它模糊救回。
        bridge = getattr(self, "_bilingual_bridge_v11216", None)
        if callable(bridge):
            try:
                rescued, bridge_reason = bridge(subscribe, candidate, info, template)
            except Exception:
                rescued, bridge_reason = False, ""
            if rescued:
                return True, f"迅雷电影真实 payload 双语闭环通过：{str(bridge_reason or '')[:300]}"

        return False, (
            "迅雷电影真实 payload 身份拒绝："
            + str(assessment.get("reason") or "实际标题未命中 MoviePilot/TMDB 官方别名")[:320]
        )


__all__ = [
    "GuangYaMediaMatchV11219Mixin",
    "movie_actual_match_v11219",
    "source_claim_episodes_v11219",
]
