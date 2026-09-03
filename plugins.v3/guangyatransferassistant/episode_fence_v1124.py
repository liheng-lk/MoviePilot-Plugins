"""v1.10.24 跨来源集级完成栅栏。

解决“某一集已经由迅雷秒传成功，后续光鸭分享/Magnet/ED2K 又把同一集再存一次”的竞态：
- 成功集号一旦进入 media_facts，立即成为所有来源共享的终态事实；
- 缺集计算、pending reservation、光鸭分享文件筛选都实时扣除终态集；
- Magnet/ED2K 在 create/retry 前重新读取当前缺集，已覆盖任务直接停止，部分重叠任务先取消旧 task 再按剩余集重建；
- 同一订阅的迅雷/分享主流程与外部云添加提交共用一把媒体级锁，避免两个来源同时越过缺集门禁。

这里的“停止”是集级而不是整部剧级：E04 成功后只封死 E04，E05/E06 仍可继续由后续来源补齐。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Set, Tuple

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _is_subtitle, _is_video


_ACTIVE_OFFLINE_STATES_V1124 = {"new", "retry", "dispatching", "submitted", "queued", "waiting"}
_PENDING_SHARE_STATES_V1124 = {"planned", "submitted", "task_confirmed", "verifying"}


def _safe_int_v1124_fence(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


class GuangYaEpisodeFenceV1124Mixin:
    """所有获取来源共用的“成功一集即封死一集”最终门禁。"""

    build_id = "20260903-r40"

    def init_plugin(self, config: dict = None) -> None:
        self._episode_fence_guard_v1124 = threading.Lock()
        self._episode_fence_locks_v1124: Dict[str, threading.RLock] = {}
        return super().init_plugin(config)

    def _episode_fence_lock_v1124(self, subscribe: Any) -> threading.RLock:
        key = self._media_fact_prefix(subscribe)
        guard = getattr(self, "_episode_fence_guard_v1124", None)
        locks = getattr(self, "_episode_fence_locks_v1124", None)
        if guard is None or locks is None:
            self._episode_fence_guard_v1124 = threading.Lock()
            self._episode_fence_locks_v1124 = {}
            guard = self._episode_fence_guard_v1124
            locks = self._episode_fence_locks_v1124
        with guard:
            lock = locks.get(key)
            if lock is None:
                lock = threading.RLock()
                locks[key] = lock
            return lock

    def _acquired_episode_facts_v1124(self, subscribe: Any) -> Set[int]:
        if not subscribe or self._is_movie_subscription(subscribe):
            return set()
        prefix = self._media_fact_prefix(subscribe) + ":e"
        facts = self.get_data("media_facts") or {}
        acquired: Set[int] = set()
        if not isinstance(facts, dict):
            return acquired
        for key in facts.keys():
            text = str(key or "")
            if not text.startswith(prefix):
                continue
            suffix = text[len(prefix):]
            if suffix.isdigit() and int(suffix) > 0:
                acquired.add(int(suffix))
        return acquired

    def _subscription_missing_episodes(self, subscribe: Any) -> List[int]:
        """即使 SubscribeOper/note 暂时未刷新，也绝不把成功回执集重新视为缺集。"""
        parent_missing = {
            _safe_int_v1124_fence(value)
            for value in (super()._subscription_missing_episodes(subscribe) or [])
            if _safe_int_v1124_fence(value) > 0
        }
        return sorted(parent_missing - self._acquired_episode_facts_v1124(subscribe))

    def _pending_reservations(self, subscribe: Any, exclude_job_key: str = "") -> Dict[str, Any]:
        """把“已成功”与“正在处理”统一成来源规划不可再次占用的集级栅栏。"""
        base = dict(super()._pending_reservations(subscribe, exclude_job_key=exclude_job_key) or {})
        base["paths"] = set(base.get("paths") or set())
        base["episodes"] = set(base.get("episodes") or set())
        if self._is_movie_subscription(subscribe):
            try:
                base["movie"] = bool(base.get("movie")) or bool(self._movie_transfer_confirmed(subscribe))
            except Exception:
                base["movie"] = bool(base.get("movie"))
        else:
            base["episodes"].update(self._acquired_episode_facts_v1124(subscribe))
        return base

    @staticmethod
    def _planned_path_v1124(item: Dict[str, Any]) -> str:
        return str(
            item.get("effective_path")
            or item.get("relative_path")
            or item.get("path")
            or item.get("name")
            or ""
        ).replace("\\", "/").strip()

    def _resolved_item_episodes_v1124(
        self,
        subscribe: Any,
        item: Dict[str, Any],
        package_paths: Iterable[str],
    ) -> Set[int]:
        path = self._planned_path_v1124(item)
        if not path or not (_is_video(path) or _is_subtitle(path)):
            return set()
        result = resolve_episode(
            path,
            package_paths=list(package_paths or []),
            season_hint=getattr(subscribe, "season", None),
        )
        threshold = float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)
        return set(reliable_episode_set(result, threshold))

    def _filter_inflight_planned_items(
        self,
        subscribe: Any,
        planned: List[Dict[str, Any]],
        exclude_job_key: str = "",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """光鸭分享最终提交前再次按成功集号裁剪；多集文件与成功集重叠时整体拒绝。"""
        ready, held = super()._filter_inflight_planned_items(
            subscribe,
            planned,
            exclude_job_key=exclude_job_key,
        )
        if not ready:
            return ready, held
        if self._is_movie_subscription(subscribe):
            if bool(self._pending_reservations(subscribe, exclude_job_key=exclude_job_key).get("movie")):
                blocked = [item for item in ready if _is_video(self._planned_path_v1124(item)) or _is_subtitle(self._planned_path_v1124(item))]
                keep = [item for item in ready if item not in blocked]
                return keep, [*held, *blocked]
            return ready, held

        acquired = self._acquired_episode_facts_v1124(subscribe)
        if not acquired:
            return ready, held
        package_paths = [self._planned_path_v1124(item) for item in ready if self._planned_path_v1124(item)]
        keep: List[Dict[str, Any]] = []
        blocked: List[Dict[str, Any]] = []
        blocked_episodes: Set[int] = set()
        for item in ready:
            episodes = self._resolved_item_episodes_v1124(subscribe, item, package_paths)
            overlap = episodes.intersection(acquired)
            if overlap:
                blocked.append(item)
                blocked_episodes.update(overlap)
            else:
                keep.append(item)
        if blocked:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【集级终止】#%s 光鸭分享提交前拦截 %s 个重复文件；已成功集=%s",
                int(getattr(subscribe, "id", 0) or 0),
                len(blocked),
                ",".join(f"E{value:02d}" for value in sorted(blocked_episodes)),
            )
        return keep, [*held, *blocked]

    @staticmethod
    def _source_episode_targets_v1124(source: Dict[str, Any]) -> Set[int]:
        values: Set[int] = set()
        for field in ("resolved_episodes", "target_episodes"):
            for raw in source.get(field) or []:
                value = _safe_int_v1124_fence(raw)
                if value > 0:
                    values.add(value)
        return values

    def _delete_offline_task_v1124(self, source: Dict[str, Any]) -> bool:
        task_id = str(source.get("task_id") or "").strip()
        if not task_id:
            return True
        try:
            response = self._offline_request(
                "/cloudcollection/v2/delete_task",
                {"taskIds": [task_id]},
            )
            return bool(self._offline_api_success(response))
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【集级终止】取消重复云添加 task=%s 失败：%s",
                task_id,
                str(err)[:260],
            )
            return False

    def _disable_offline_source_v1124(
        self,
        source: Dict[str, Any],
        acquired: Set[int],
        *,
        reason: str,
    ) -> Dict[str, Any]:
        source_id = str(source.get("id") or "")
        state = str(source.get("state") or "")
        remote_cancelled = True
        if str(source.get("task_id") or "").strip() and state in _ACTIVE_OFFLINE_STATES_V1124:
            remote_cancelled = self._delete_offline_task_v1124(source)
        updated = self._update_source(
            source_id,
            state="disabled",
            enabled=False,
            auto_dispatch=False,
            superseded_by_receipt=True,
            superseded_episodes=sorted(acquired),
            superseded_at=self._now_text(),
            superseded_reason=str(reason)[:400],
            remote_cancelled=bool(remote_cancelled),
            next_retry_at=0,
        ) or source
        self._plugin_log(
            "INFO" if remote_cancelled else "WARNING",
            "【光鸭转存助手】【集级终止】来源 %s 已停止：%s；服务端任务取消=%s",
            source_id or "-",
            reason,
            remote_cancelled,
        )
        return updated

    def _supersede_offline_sources_v1124(self, subscribe: Any, acquired: Set[int]) -> int:
        if not acquired:
            return 0
        sid = int(getattr(subscribe, "id", 0) or 0)
        store_method = getattr(self, "_source_store", None)
        if sid <= 0 or not callable(store_method):
            return 0
        try:
            items = dict((store_method().get("items") or {}))
        except Exception:
            return 0
        stopped = 0
        for source in items.values():
            if not isinstance(source, dict) or int(source.get("subscribe_id") or 0) != sid:
                continue
            state = str(source.get("state") or "")
            if state not in _ACTIVE_OFFLINE_STATES_V1124:
                continue
            targets = self._source_episode_targets_v1124(source)
            if not targets:
                continue
            remaining = targets - acquired
            if not remaining:
                self._disable_offline_source_v1124(
                    source,
                    acquired,
                    reason="目标集已被其它成功来源确认获得",
                )
                stopped += 1
                continue
            # 尚未创建服务端任务时可以安全把目标缩小到真正剩余的集数。
            if remaining != targets and not str(source.get("task_id") or "").strip() and state in {"new", "retry"}:
                self._update_source(
                    str(source.get("id") or ""),
                    target_episodes=sorted(remaining),
                    superseded_episodes=sorted(targets.intersection(acquired)),
                    superseded_at=self._now_text(),
                )
        return stopped

    def _supersede_share_jobs_v1124(self, subscribe: Any, acquired: Set[int]) -> int:
        """旧的待确认分享任务若全部集数都已被成功回执覆盖，则不再重放。"""
        if not acquired:
            return 0
        prefix = self._media_fact_prefix(subscribe)
        jobs = self.get_data("transfer_jobs") or {}
        if not isinstance(jobs, dict):
            return 0
        changed = 0
        for key, raw in list(jobs.items()):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("media") or "") != prefix or str(raw.get("status") or "") not in _PENDING_SHARE_STATES_V1124:
                continue
            paths = [str(value or "") for value in (raw.get("paths") or []) if str(value or "").strip()]
            if not paths:
                continue
            episodes: Set[int] = set()
            for path in paths:
                episodes.update(self._resolved_item_episodes_v1124(subscribe, {"path": path}, paths))
            if not episodes or not episodes.issubset(acquired):
                continue
            row = dict(raw)
            row["status"] = "superseded"
            row["superseded_episodes"] = sorted(episodes)
            row["superseded_at"] = self._now_text()
            row["cancel_reason"] = "这些集已由其它来源成功存入，旧待确认任务不再重放"
            jobs[key] = row
            changed += 1
        if changed:
            self.save_data("transfer_jobs", jobs)
        return changed

    def _commit_episode_receipt_v1124(self, subscribe: Any, episodes: Iterable[int], origin: str) -> None:
        values = {
            _safe_int_v1124_fence(value)
            for value in episodes
            if _safe_int_v1124_fence(value) > 0
        }
        if not values or self._is_movie_subscription(subscribe):
            return
        sid = int(getattr(subscribe, "id", 0) or 0)
        fresh = self._find_subscription(sid) if sid else None
        current = fresh or subscribe
        # 先把 media_facts 立即回写 MoviePilot note/lack，再以同一事实终止其它来源。
        try:
            self._sync_media_facts_progress(current)
        except Exception as err:
            self._plugin_log("WARNING", "【光鸭转存助手】【集级终止】#%s 回写订阅进度失败：%s", sid, str(err)[:260])
        acquired = self._acquired_episode_facts_v1124(current)
        stopped_sources = self._supersede_offline_sources_v1124(current, acquired)
        stopped_jobs = self._supersede_share_jobs_v1124(current, acquired)
        missing = self._subscription_missing_episodes(current)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【集级终止】#%s 成功回执=%s origin=%s；订阅已完成集立即增加，剩余=%s；停止重复来源=%s/旧任务=%s",
            sid,
            ",".join(f"E{value:02d}" for value in sorted(values)),
            origin,
            ",".join(f"E{value:02d}" for value in missing) or "无",
            stopped_sources,
            stopped_jobs,
        )
        if not missing:
            try:
                self._finish_subscription_if_complete(current)
            except Exception:
                pass

    def _remember_episode_facts(self, subscribe: Any, episodes: Iterable[int], origin: str = "library") -> int:
        values = sorted({
            _safe_int_v1124_fence(value)
            for value in episodes
            if _safe_int_v1124_fence(value) > 0
        })
        changed = super()._remember_episode_facts(subscribe, values, origin=origin)
        if values and not self._is_movie_subscription(subscribe):
            self._commit_episode_receipt_v1124(subscribe, values, origin)
        return changed

    def _remember_media_facts(self, subscribe: Any, items: List[Dict[str, Any]], origin: str = "transfer") -> int:
        """光鸭直接分享成功也统一转换成高置信集级回执，而不是只记文件路径。"""
        changed = super()._remember_media_facts(subscribe, items, origin=origin)
        if not items or self._is_movie_subscription(subscribe):
            return changed
        package_paths = [self._planned_path_v1124(item) for item in items if self._planned_path_v1124(item)]
        episodes: Set[int] = set()
        for item in items:
            if not _is_video(self._planned_path_v1124(item)):
                continue
            episodes.update(self._resolved_item_episodes_v1124(subscribe, item, package_paths))
        if episodes:
            self._remember_episode_facts(subscribe, episodes, origin=f"{origin}_receipt")
        return changed

    def _prepare_offline_source_v1124(self, source: Dict[str, Any], subscribe: Any) -> Tuple[bool, Dict[str, Any], str]:
        """create/retry 前最后一次按当前缺集裁剪，防止旧计划把成功集再次提交。"""
        source_id = str(source.get("id") or "")
        targets = self._source_episode_targets_v1124(source)
        if self._is_movie_subscription(subscribe):
            try:
                if self._movie_transfer_confirmed(subscribe):
                    updated = self._disable_offline_source_v1124(source, set(), reason="电影正片已经成功获得")
                    return False, updated, "电影已完成，停止重复云添加"
            except Exception:
                pass
            return True, source, ""
        if not targets:
            return True, source, ""

        missing = set(self._subscription_missing_episodes(subscribe))
        remaining = targets.intersection(missing)
        acquired = targets - remaining
        if not remaining:
            updated = self._disable_offline_source_v1124(
                source,
                self._acquired_episode_facts_v1124(subscribe),
                reason="该来源目标集均已成功获得",
            )
            return False, updated, "目标集已完成，停止重复云添加"
        if remaining == targets:
            return True, source, ""

        task_id = str(source.get("task_id") or "").strip()
        if task_id:
            # 已经创建的 cloudcollection 任务无法安全改 fileIndexes：先取消旧任务，再重建剩余集。
            if not self._delete_offline_task_v1124(source):
                updated = self._disable_offline_source_v1124(
                    source,
                    self._acquired_episode_facts_v1124(subscribe),
                    reason="旧任务包含已完成集且无法安全裁剪，宁可停止等待其它来源，也不重复入库",
                )
                return False, updated, "旧任务无法裁剪，已停止以避免重复"
            source = self._update_source(
                source_id,
                state="new",
                task_id="",
                task_status=0,
                progress=0,
                target_episodes=sorted(remaining),
                selected_indexes=[],
                next_retry_at=0,
                superseded_episodes=sorted(acquired),
                superseded_at=self._now_text(),
            ) or source
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【集级终止】来源 %s 旧云添加任务已取消；仅按剩余 %s 重新解析提交",
                source_id,
                ",".join(f"E{value:02d}" for value in sorted(remaining)),
            )
            return True, source, ""

        source = self._update_source(
            source_id,
            target_episodes=sorted(remaining),
            superseded_episodes=sorted(acquired),
            superseded_at=self._now_text(),
        ) or source
        return True, source, ""

    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        store = self._source_store()
        source = dict((store.get("items") or {}).get(source_id) or {})
        if not source:
            return {"success": False, "message": "来源不存在"}
        subscribe = self._find_subscription(int(source.get("subscribe_id") or 0))
        if not subscribe:
            return super()._submit_offline_source(source_id)
        lock = self._episode_fence_lock_v1124(subscribe)
        with lock:
            latest = dict((self._source_store().get("items") or {}).get(source_id) or source)
            fresh = self._find_subscription(int(latest.get("subscribe_id") or 0)) or subscribe
            allowed, prepared, message = self._prepare_offline_source_v1124(latest, fresh)
            if not allowed:
                return {"success": True, "handled": True, "message": message, "data": prepared}
            return super()._submit_offline_source(source_id)

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        source_id = str(source.get("id") or "")
        latest = dict((self._source_store().get("items") or {}).get(source_id) or source)
        subscribe = self._find_subscription(int(latest.get("subscribe_id") or 0))
        if not subscribe:
            return super()._poll_offline_source(latest)
        lock = self._episode_fence_lock_v1124(subscribe)
        with lock:
            latest = dict((self._source_store().get("items") or {}).get(source_id) or latest)
            fresh = self._find_subscription(int(latest.get("subscribe_id") or 0)) or subscribe
            allowed, prepared, message = self._prepare_offline_source_v1124(latest, fresh)
            if not allowed:
                return {"success": True, "handled": True, "message": message, "data": prepared}
            return super()._poll_offline_source(latest)

    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        """同一媒体的迅雷→分享→Magnet/ED2K 规划串行通过同一缺集栅栏。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        current = self._find_subscription(sid) if sid else None
        current = current or subscribe
        lock = self._episode_fence_lock_v1124(current)
        with lock:
            if not self._is_movie_subscription(current):
                try:
                    self._sync_media_facts_progress(current)
                except Exception:
                    pass
            result = super()._try_transfer_subscription_inner(
                current,
                force=force,
                refresh_channel=refresh_channel,
            )
            fresh = self._find_subscription(sid) if sid else None
            if fresh and not self._is_movie_subscription(fresh):
                try:
                    self._sync_media_facts_progress(fresh)
                except Exception:
                    pass
            return result


__all__ = ["GuangYaEpisodeFenceV1124Mixin"]
