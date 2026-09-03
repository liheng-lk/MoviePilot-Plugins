"""v1.9.0 ResourceGroup 决策与缺集拆包层。

决策原则：
1. 先确定订阅当前真正缺什么；
2. 同一 Telegram 消息中的光鸭分享 / Magnet / ED2K 是同一 ResourceGroup 的候选；
3. 同等满足订阅规则时，光鸭直接转存优先；其正在落盘的剧集会被 reservation 占用；
4. 只对剩余未覆盖剧集选择 Magnet，其次 ED2K；
5. Magnet resolve 后按高置信集号只选缺集文件，无法可靠识别时不整包误存；
6. 已创建 taskId 永远由既有 v1.8.0 安全层轮询，不重复 create_task。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _entry_match_reason, _is_subtitle, _is_video
from .source_types_v180 import source_identity


_AMBIGUOUS_PREFIX = "EPISODE_AMBIGUOUS:"
_ACTIVE_CLAIM_STATES = {"new", "retry", "dispatching", "submitted", "queued", "waiting", "completed"}


class GuangYaResourcePlannerMixin:
    """必须放在 OfflineSafety / MultiSource 之前，让所有来源共用同一决策。"""

    _episode_auto_confidence = AUTO_SELECT_CONFIDENCE
    _channel_external_auto_dispatch = True

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        try:
            threshold = float(config.get("episode_auto_confidence", AUTO_SELECT_CONFIDENCE))
        except (TypeError, ValueError):
            threshold = AUTO_SELECT_CONFIDENCE
        self._episode_auto_confidence = max(0.80, min(threshold, 1.0))
        self._channel_external_auto_dispatch = bool(config.get("channel_external_auto_dispatch", True))
        super().init_plugin(config)

    # ------------------------------------------------------------------
    # 来源元数据 / ResourceGroup
    # ------------------------------------------------------------------
    def _upsert_source(
        self,
        subscribe_id: int,
        uri: str,
        *,
        label: str = "",
        origin: str = "manual",
        enabled: bool = True,
        auto_dispatch: Optional[bool] = None,
        resource_group_id: str = "",
        target_episodes: Optional[Iterable[int]] = None,
        episode_hint: str = "",
        source_label: str = "",
        message_id: str = "",
        candidate_rank: int = 0,
    ) -> Dict[str, Any]:
        row = super()._upsert_source(
            subscribe_id,
            uri,
            label=label,
            origin=origin,
            enabled=enabled,
            auto_dispatch=auto_dispatch,
        )
        extras: Dict[str, Any] = {}
        if resource_group_id:
            extras["resource_group_id"] = str(resource_group_id)[:80]
        if target_episodes is not None:
            values = []
            for raw in target_episodes:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
                if value > 0 and value not in values:
                    values.append(value)
            extras["target_episodes"] = sorted(values)
        if episode_hint:
            extras["episode_hint"] = str(episode_hint)[:120]
        if source_label:
            extras["source_label"] = str(source_label)[:120]
        if message_id:
            extras["message_id"] = str(message_id)[:80]
        extras["candidate_rank"] = int(candidate_rank or 0)
        if extras:
            row = self._update_source(str(row.get("id") or ""), **extras) or row
        return row

    def _existing_source(self, subscribe_id: int, source_type: str, identity: str) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        key = source_identity(str(source_type or ""), str(identity or ""), sid)
        return dict(self._source_store()["items"].get(key) or {})

    def _active_source_claims(self, subscribe_id: int) -> set[int]:
        claims: set[int] = set()
        sid = int(subscribe_id or 0)
        for row in self._source_store()["items"].values():
            if not isinstance(row, dict) or int(row.get("subscribe_id") or 0) != sid:
                continue
            if str(row.get("state") or "new") not in _ACTIVE_CLAIM_STATES:
                continue
            for raw in row.get("resolved_episodes") or row.get("target_episodes") or []:
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    claims.add(value)
        return claims

    @staticmethod
    def _source_descriptor(source: Dict[str, Any]) -> str:
        return " ".join(
            str(value or "")
            for value in (source.get("name"), source.get("label"), source.get("type"))
            if value
        )

    def _external_resource_allowed(
        self,
        subscribe: Any,
        entry: Dict[str, Any],
        source: Dict[str, Any],
    ) -> Tuple[bool, str]:
        # 复用 legacy 的 include/exclude/resolution/quality/effect 规则，保证分享与磁力判断一致。
        descriptor_name = self._source_descriptor(source)
        probe = {"files": [{"relative_path": descriptor_name, "name": descriptor_name}]}
        return self._subscription_resource_allowed(subscribe, entry, probe)

    # ------------------------------------------------------------------
    # Magnet resolve 后的文件级缺集选择
    # ------------------------------------------------------------------
    @staticmethod
    def _media_rows(resolve_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        bt_info = resolve_data.get("btResInfo") or {}
        if not isinstance(bt_info, dict):
            return []
        subfiles = bt_info.get("subfiles") or []
        if not isinstance(subfiles, list):
            return []
        rows = []
        for fallback_index, raw in enumerate(subfiles):
            if not isinstance(raw, dict):
                continue
            value = raw.get("fileIndex")
            try:
                index = int(value) if value is not None else fallback_index
            except (TypeError, ValueError):
                index = fallback_index
            name = str(raw.get("fileName") or "").replace("\\", "/").strip()
            try:
                size = int(raw.get("fileSize") or 0)
            except (TypeError, ValueError):
                size = 0
            rows.append({
                "index": index,
                "name": name,
                "size": size,
                "video": _is_video(name),
                "subtitle": _is_subtitle(name),
            })
        return rows

    @staticmethod
    def _parent_path(value: str) -> str:
        normalized = str(value or "").replace("\\", "/")
        return normalized.rsplit("/", 1)[0].lower() if "/" in normalized else ""

    def _planner_file_selection(
        self,
        source: Dict[str, Any],
        subscribe: Any,
        resolve_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        rows = self._media_rows(resolve_data)
        media_rows = [row for row in rows if row["video"] or row["subtitle"]]
        if not rows:
            return {"indexes": [], "episodes": [], "diagnostics": [], "ambiguous": False}

        # 电影不存在“按集拆包”，继续尊重 media_only；有媒体文件时只保存媒体相关文件。
        if self._is_movie_subscription(subscribe):
            if bool(getattr(self, "_media_only", True)):
                indexes = [int(row["index"]) for row in media_rows]
            else:
                indexes = [int(row["index"]) for row in rows]
            return {"indexes": list(dict.fromkeys(indexes)), "episodes": [], "diagnostics": [], "ambiguous": False}

        missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe) or []) if int(v or 0) > 0)
        reserved = set(int(v) for v in (self._pending_reservations(subscribe).get("episodes") or set()) if int(v or 0) > 0)
        configured_target = set()
        for raw in source.get("target_episodes") or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                configured_target.add(value)
        target = (configured_target or missing).intersection(missing) - reserved
        if not target:
            return {"indexes": [], "episodes": [], "diagnostics": ["当前目标剧集已被其它任务覆盖或已完成"], "ambiguous": False, "covered": True}

        package_paths = [str(row["name"]) for row in media_rows]
        season_hint = getattr(subscribe, "season", None)
        episode_hint = str(source.get("episode_hint") or "")
        threshold = float(self._episode_auto_confidence or AUTO_SELECT_CONFIDENCE)

        resolutions: Dict[int, Dict[str, Any]] = {}
        diagnostics: List[str] = []
        for row in media_rows:
            result = resolve_episode(
                row["name"],
                package_paths=package_paths,
                season_hint=season_hint,
                episode_hint=episode_hint,
            )
            resolutions[int(row["index"])] = result
            eps = reliable_episode_set(result, threshold)
            diagnostics.append(
                f"{row['name']} => {','.join('E%02d' % value for value in sorted(eps)) or '?'} "
                f"({float(result.get('confidence') or 0):.2f}, {result.get('reason') or '-'})"
            )

        selected_videos: List[Dict[str, Any]] = []
        covered: set[int] = set()
        unresolved_videos: List[str] = []
        for row in media_rows:
            if not row["video"]:
                continue
            result = resolutions.get(int(row["index"])) or {}
            episodes = reliable_episode_set(result, threshold)
            hit = episodes.intersection(target)
            if hit:
                selected_videos.append(row)
                covered.update(hit)
            elif not episodes:
                unresolved_videos.append(str(row["name"]))

        # 单文件 + 帖子明确单集时允许上下文推断；除此之外绝不把 A.mkv/B.mkv 按顺序猜成集号。
        if not selected_videos:
            video_rows = [row for row in media_rows if row["video"]]
            hint_result = resolve_episode(episode_hint, season_hint=season_hint) if episode_hint else {}
            hinted = reliable_episode_set(hint_result, 0.99)
            if len(video_rows) == 1 and len(target) == 1 and hinted == target:
                selected_videos = [video_rows[0]]
                covered = set(target)
                diagnostics.append(f"{video_rows[0]['name']} => 上下文明示单集 {sorted(target)}")
            else:
                detail = "；".join(unresolved_videos[:6]) or "没有文件能高置信映射到当前缺集"
                return {
                    "indexes": [],
                    "episodes": [],
                    "diagnostics": diagnostics,
                    "ambiguous": True,
                    "message": detail,
                }

        indexes: List[int] = [int(row["index"]) for row in selected_videos]

        # 字幕必须能映射到已选择剧集；弱命名字幕仅在同目录只有一个已选视频时保守跟随。
        videos_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        for row in selected_videos:
            videos_by_parent.setdefault(self._parent_path(str(row["name"])), []).append(row)
        for row in media_rows:
            if not row["subtitle"]:
                continue
            result = resolutions.get(int(row["index"])) or {}
            episodes = reliable_episode_set(result, threshold)
            if episodes.intersection(covered):
                indexes.append(int(row["index"]))
                continue
            parent = self._parent_path(str(row["name"]))
            if not episodes and len(videos_by_parent.get(parent) or []) == 1:
                indexes.append(int(row["index"]))

        return {
            "indexes": list(dict.fromkeys(indexes)),
            "episodes": sorted(covered),
            "diagnostics": diagnostics,
            "ambiguous": False,
        }

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        response = self._offline_request(
            "/cloudcollection/v1/resolve_res",
            {"url": str(source.get("uri") or "")},
        )
        if not self._offline_api_success(response):
            raise RuntimeError(self._offline_api_error(response, "光鸭云添加解析失败"))
        data = self._offline_resolved_data(response)
        bt_info = data.get("btResInfo") or {}
        resolved_name = ""
        if isinstance(bt_info, dict):
            resolved_name = str(bt_info.get("fileName") or "").strip()
        resolved_name = resolved_name or str(source.get("name") or source.get("label") or "").strip()
        resolved_url = str(data.get("url") or source.get("uri") or "").strip()

        selection = self._planner_file_selection(source, subscribe, data)
        indexes = list(selection.get("indexes") or [])
        subfiles = bt_info.get("subfiles") if isinstance(bt_info, dict) else None

        # ED2K 通常是“单文件云添加”，resolve_res 不一定返回 btResInfo.subfiles。
        # 旧逻辑在这种情况下会创建任务，但 resolved_episodes 为空；完成后无法把该集
        # 写回 MoviePilot，也可能让后续扫描再次命中同一集。现在用真实 resolve 文件名
        # + 频道 episode_hint 做最后一次高置信集号确认，并把实际命中的缺集回填。
        source_type = str(source.get("type") or "").strip().lower()
        no_subfiles = not (isinstance(subfiles, list) and subfiles)
        if source_type == "ed2k" and not self._is_movie_subscription(subscribe) and no_subfiles:
            season_hint = getattr(subscribe, "season", None)
            episode_hint = str(source.get("episode_hint") or "").strip()
            actual_names = []
            for value in (resolved_name, bt_info.get("fileName") if isinstance(bt_info, dict) else ""):
                value = str(value or "").strip()
                if value and value not in actual_names:
                    actual_names.append(value)
            actual_episodes = set()
            threshold = float(self._episode_auto_confidence or AUTO_SELECT_CONFIDENCE)
            for value in actual_names:
                result = resolve_episode(
                    value,
                    package_paths=actual_names,
                    season_hint=season_hint,
                    episode_hint=episode_hint,
                )
                actual_episodes.update(reliable_episode_set(result, threshold))
            if not actual_episodes and episode_hint:
                hinted = resolve_episode(episode_hint, season_hint=season_hint)
                actual_episodes.update(reliable_episode_set(hinted, 0.99))

            missing_now = {
                int(value) for value in (self._subscription_missing_episodes(subscribe) or [])
                if int(value or 0) > 0
            }
            configured_target = {
                int(value) for value in (source.get("target_episodes") or [])
                if str(value).isdigit() and int(value) > 0
            }
            allowed_target = (configured_target or missing_now).intersection(missing_now)
            matched_episodes = actual_episodes.intersection(allowed_target)
            if not matched_episodes:
                detail = ", ".join(actual_names[:2]) or str(source.get("name") or "ED2K 单文件")
                raise RuntimeError(
                    f"{_AMBIGUOUS_PREFIX}ED2K 已解析但真实文件无法确认覆盖当前缺集：{detail}"
                )
            selection["episodes"] = sorted(matched_episodes)
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【频道云添加】ED2K 单文件解析命中缺集=%s，允许提交光鸭 cloudcollection",
                ",".join(f"E{value:02d}" for value in sorted(matched_episodes)),
            )
        if not self._is_movie_subscription(subscribe) and bool(selection.get("covered")) and not indexes:
            raise RuntimeError(f"{_AMBIGUOUS_PREFIX}当前缺集已被其它在途任务覆盖，暂不创建重复离线任务")
        if bool(selection.get("ambiguous")):
            detail = str(selection.get("message") or "文件集号无法可靠识别")
            raise RuntimeError(f"{_AMBIGUOUS_PREFIX}{detail}")
        if bool(getattr(self, "_media_only", True)) and isinstance(subfiles, list) and subfiles and not indexes:
            raise RuntimeError(f"{_AMBIGUOUS_PREFIX}光鸭已解析来源，但没有高置信匹配当前缺集的视频文件")

        source_id = str(source.get("id") or "")
        if source_id:
            self._update_source(
                source_id,
                resolved_episodes=list(selection.get("episodes") or []),
                selection_diagnostics=list(selection.get("diagnostics") or [])[:80],
                selection_confidence=float(self._episode_auto_confidence or AUTO_SELECT_CONFIDENCE),
            )
        return {
            "resolved_name": resolved_name[:300],
            "resolved_url": resolved_url,
            "selected_indexes": indexes,
            "resolve_data": data,
        }

    def _mark_offline_failure(
        self,
        source: Dict[str, Any],
        error: Exception | str,
        *,
        attempt_increment: bool = True,
    ) -> Dict[str, Any]:
        message = str(error or "")
        if message.startswith(_AMBIGUOUS_PREFIX):
            detail = message[len(_AMBIGUOUS_PREFIX):].strip() or "集号无法可靠识别"
            updated = self._update_source(
                str(source.get("id") or ""),
                state="needs_review",
                last_error=detail[:500],
                next_retry_at=0,
            ) or source
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【拆包保护】来源 %s 未创建离线任务：%s",
                str(source.get("id") or ""),
                detail,
            )
            return updated
        return super()._mark_offline_failure(source, error, attempt_increment=attempt_increment)

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        result = super()._poll_offline_source(source)
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict) or str(data.get("state") or "") != "completed":
            return result
        latest = dict(self._source_store()["items"].get(str(source.get("id") or "")) or data)
        episodes = []
        for raw in latest.get("resolved_episodes") or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                episodes.append(value)
        if episodes:
            subscribe = self._find_subscription(int(latest.get("subscribe_id") or 0))
            if subscribe:
                self._remember_episode_facts(subscribe, episodes, origin="guangya_offline")
                self._sync_media_facts_progress(subscribe)
        return result

    # ------------------------------------------------------------------
    # 同一资源多候选的决策与回退
    # ------------------------------------------------------------------
    def _candidate_target_episodes(
        self,
        subscribe: Any,
        entry: Dict[str, Any],
        source: Dict[str, Any],
        uncovered: set[int],
    ) -> set[int]:
        source_name = str(source.get("name") or "")
        hint = str(entry.get("episode_hint") or "")
        result = resolve_episode(
            source_name,
            season_hint=getattr(subscribe, "season", None),
            episode_hint=hint,
        )
        explicit = reliable_episode_set(result, float(self._episode_auto_confidence or AUTO_SELECT_CONFIDENCE))
        if explicit:
            return explicit.intersection(uncovered)

        hint_result = resolve_episode(hint, season_hint=getattr(subscribe, "season", None)) if hint else {}
        hinted = reliable_episode_set(hint_result, 0.99)
        if hinted:
            return hinted.intersection(uncovered)

        # Magnet/ED2K 都允许先进入光鸭 resolve：
        # - Magnet 常见整季/更新包，需要解析内部文件后才能确认缺集；
        # - ED2K 是单文件链接，频道标题或文件名可能不带可直接识别的集号，
        #   但 resolve 后的真实文件名仍可安全确认。这里只做“待解析候选”，
        #   最终集号仍必须在 _resolve_offline_source 中回填并通过缺集门禁。
        if str(source.get("type") or "") in {"magnet", "ed2k"}:
            return set(uncovered)
        return set()

    def _save_resource_plan(self, subscribe: Any, payload: Dict[str, Any]) -> None:
        sid = str(int(getattr(subscribe, "id", 0) or 0))
        plans = self.get_data("resource_plans") or {}
        plans[sid] = {
            **dict(payload or {}),
            "subscribe_id": int(sid or 0),
            "name": str(getattr(subscribe, "name", "") or ""),
            "updated_at": self._now_text(),
        }
        if len(plans) > 500:
            ordered = sorted(plans.items(), key=lambda pair: str((pair[1] or {}).get("updated_at") or ""), reverse=True)[:500]
            plans = dict(ordered)
        self.save_data("resource_plans", plans)

    def _dispatch_channel_external_candidates(self, subscribe: Any) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid or not self._channel_external_auto_dispatch:
            return {"success": True, "actions": [], "message": "频道外部候选自动调度已关闭"}

        is_movie = self._is_movie_subscription(subscribe)
        reservations = self._pending_reservations(subscribe)
        if is_movie and bool(reservations.get("movie")):
            self._save_resource_plan(subscribe, {"movie": True, "waiting_share": True, "actions": []})
            return {"success": True, "actions": [], "message": "光鸭直接转存正在落盘，外部候选保持备用"}

        missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe) or []) if int(v or 0) > 0)
        reserved = set(int(v) for v in (reservations.get("episodes") or set()) if int(v or 0) > 0)
        active_claims = self._active_source_claims(sid)
        uncovered = missing - reserved - active_claims

        if not is_movie and not uncovered:
            self._save_resource_plan(subscribe, {
                "missing": sorted(missing),
                "reserved_by_share": sorted(reserved),
                "claimed_by_external": sorted(active_claims),
                "uncovered": [],
                "actions": [],
            })
            return {"success": True, "actions": [], "message": "当前缺集已由已完成/在途任务覆盖"}

        # 电影已有任何活跃外部来源时不再创建第二个候选任务。
        if is_movie:
            active_movie = any(
                isinstance(row, dict)
                and int(row.get("subscribe_id") or 0) == sid
                and str(row.get("state") or "new") in _ACTIVE_CLAIM_STATES
                for row in self._source_store()["items"].values()
            )
            if active_movie:
                return {"success": True, "actions": [], "message": "电影已有外部获取任务"}

        entries = list((self.get_data("channel_index") or {}).get("items") or [])
        matched_entries = []
        for entry in entries:
            external = list(entry.get("external_sources") or []) if isinstance(entry, dict) else []
            if not external or entry.get("stale"):
                continue
            matched, reason = _entry_match_reason(entry, subscribe)
            if matched:
                matched_entries.append((entry, reason))

        actions = []
        skipped = []
        magnet_selected = False
        for entry, match_reason in matched_entries:
            external = list(entry.get("external_sources") or [])
            external.sort(key=lambda row: 0 if str(row.get("type") or "") == "magnet" else 1)
            for candidate in external:
                source_type = str(candidate.get("type") or "")
                if source_type not in {"magnet", "ed2k"}:
                    continue
                if magnet_selected and source_type == "magnet":
                    continue
                allowed, rule_reason = self._external_resource_allowed(subscribe, entry, candidate)
                if not allowed:
                    skipped.append({"type": source_type, "reason": rule_reason})
                    continue

                existing = self._existing_source(sid, source_type, str(candidate.get("identity") or ""))
                existing_state = str(existing.get("state") or "")
                if existing_state in {"failed", "needs_review", "disabled"}:
                    # 已确认不可用的候选不阻断本组下一种方式，实现 Magnet -> ED2K 回退。
                    skipped.append({"type": source_type, "reason": f"已有候选状态 {existing_state}，尝试下一候选"})
                    continue
                if existing and existing_state in _ACTIVE_CLAIM_STATES:
                    continue

                if is_movie:
                    target = set()
                else:
                    target = self._candidate_target_episodes(subscribe, entry, candidate, uncovered)
                    if not target:
                        continue

                rank = 1 if source_type == "magnet" else 2
                row = self._upsert_source(
                    sid,
                    str(candidate.get("uri") or ""),
                    label=str(candidate.get("name") or "")[:120],
                    origin="telegram",
                    auto_dispatch=True,
                    resource_group_id=str(entry.get("resource_group_id") or ""),
                    target_episodes=sorted(target),
                    episode_hint=str(entry.get("episode_hint") or ""),
                    source_label=str(entry.get("source_label") or ""),
                    message_id=str(entry.get("message_id") or ""),
                    candidate_rank=rank,
                )
                action = {
                    "resource_group_id": str(entry.get("resource_group_id") or ""),
                    "source_id": str(row.get("id") or ""),
                    "type": source_type,
                    "episodes": sorted(target),
                    "reason": f"{match_reason}；光鸭直接转存未覆盖这些目标集；候选优先级 {rank}",
                }
                actions.append(action)
                if source_type == "magnet":
                    magnet_selected = True
                if not is_movie:
                    uncovered -= target
                self._spawn_source_dispatch(str(row.get("id") or ""))
                if is_movie or not uncovered:
                    break
            if is_movie or not uncovered:
                break

        self._save_resource_plan(subscribe, {
            "missing": sorted(missing),
            "reserved_by_share": sorted(reserved),
            "claimed_by_external": sorted(active_claims),
            "uncovered": sorted(uncovered),
            "actions": actions,
            "skipped": skipped[:30],
        })
        if actions:
            return {"success": True, "actions": actions, "message": f"已生成 {len(actions)} 个外部候选执行计划"}
        return {"success": False, "actions": [], "message": "当前没有可安全执行的 Magnet/ED2K 候选"}

    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        # super 先执行成熟的光鸭分享增量转存；其 pending reservation 天然成为最高优先级占位。
        share_result = super()._try_transfer_subscription_inner(
            subscribe,
            force=force,
            refresh_channel=refresh_channel,
        )
        try:
            external = self._dispatch_channel_external_candidates(subscribe)
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【资源决策】#%s 外部候选规划失败：%s", getattr(subscribe, "id", 0), err)
            external = {"success": False, "actions": [], "message": str(err)}
        if external.get("actions"):
            return {
                **dict(share_result or {}),
                "success": True,
                "handled": True,
                "external_actions": external.get("actions"),
                "message": f"{str((share_result or {}).get('message') or '光鸭分享已检查')}；{external.get('message')}",
            }
        return share_result

    # ------------------------------------------------------------------
    # API / 状态页
    # ------------------------------------------------------------------
    def api_resource_plan(self, subscribe_id: int = 0) -> Dict[str, Any]:
        plans = self.get_data("resource_plans") or {}
        sid = str(int(subscribe_id or 0))
        if sid != "0":
            row = dict(plans.get(sid) or {})
            return {"success": bool(row), "data": row}
        rows = [dict(row) for row in plans.values() if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return {"success": True, "count": len(rows), "data": rows[:100]}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        if not any(str(item.get("path") or "") == "/resource/plan" for item in apis if isinstance(item, dict)):
            apis.append({
                "path": "/resource/plan",
                "endpoint": self.api_resource_plan,
                "methods": ["GET"],
                "summary": "查看 ResourceGroup 缺集决策计划",
            })
        return apis

    def get_form(self):
        form, defaults = super().get_form()
        try:
            content = form[0].get("content") if form else None
            if isinstance(content, list):
                content.append({
                    "component": "VCard",
                    "props": {"variant": "tonal", "class": "mt-3"},
                    "content": [
                        {"component": "VCardTitle", "text": "资源决策与安全拆包"},
                        {
                            "component": "VCardText",
                            "text": (
                                "同一频道消息按 ResourceGroup 处理：光鸭直接转存优先，Magnet 次之，ED2K 兜底。"
                                "剧集只在集号置信度达到阈值时自动拆包；无法可靠识别时不会整包误存。"
                            ),
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 6},
                                    "content": [{
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "channel_external_auto_dispatch",
                                            "label": "频道 Magnet/ED2K 自动候选",
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 6},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "episode_auto_confidence",
                                            "label": "自动拆包置信度",
                                            "type": "number",
                                            "step": "0.01",
                                            "min": "0.80",
                                            "max": "1.00",
                                        },
                                    }],
                                },
                            ],
                        },
                    ],
                })
        except Exception:
            pass
        defaults.update({
            "channel_external_auto_dispatch": self._channel_external_auto_dispatch,
            "episode_auto_confidence": self._episode_auto_confidence,
        })
        return form, defaults

    def get_page(self):
        pages = list(super().get_page() or [])
        plans = self.api_resource_plan().get("data") or []
        unresolved = [row for row in plans if row.get("uncovered")]
        recent_actions = sum(len(row.get("actions") or []) for row in plans[:20])
        card = {
            "component": "VAlert",
            "props": {
                "type": "warning" if unresolved else "success",
                "variant": "tonal",
                "title": "资源组决策 · 缺集拆包",
                "text": (
                    f"最近计划 {len(plans)} 个 · 已生成外部执行 {recent_actions} 个 · "
                    f"仍有未覆盖 {len(unresolved)} 个订阅。"
                    " 决策顺序：光鸭直接转存 > Magnet > ED2K；低置信集号不自动保存。"
                ),
            },
        }
        return [card, *pages]


__all__ = ["GuangYaResourcePlannerMixin"]
