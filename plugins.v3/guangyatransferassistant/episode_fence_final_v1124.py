"""v1.10.24 跨来源集级终止栅栏最终补丁。

补齐并发/在途边界：
- 迅雷秒传、光鸭分享、Magnet、ED2K 不只共享“已成功集”，也共享“正在处理集”；
- 外部云添加任务在提交/轮询前再次按实时缺集裁剪；部分重叠任务立即取消旧 task，
  只保留真正缺失的集数重新提交；
- 每个外部 worker 用线程局部 source_id 排除自身 reservation，避免自己的 dispatching
  状态反过来把自己判成重复；
- 修正旧栅栏在取消并重建后仍轮询旧 task_id 的边界。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Set, Tuple

from .episode_fence_v1124 import GuangYaEpisodeFenceV1124Mixin


_EXTERNAL_INFLIGHT_V1124 = {"dispatching", "submitted", "queued", "waiting"}
_EXTERNAL_ACTIVE_V1124 = {"new", "retry", "dispatching", "submitted", "queued", "waiting"}


class GuangYaEpisodeFenceFinalV1124Mixin:
    """最终运行时门禁：任何来源成功/在途后，其目标集不允许其它来源重复提交。"""

    build_id = "20260903-r40"

    def init_plugin(self, config: dict = None) -> None:
        self._episode_fence_context_v1124 = threading.local()
        return super().init_plugin(config)

    def _episode_fence_current_source_v1124(self) -> str:
        context = getattr(self, "_episode_fence_context_v1124", None)
        return str(getattr(context, "source_id", "") or "") if context is not None else ""

    def _pending_reservations(self, subscribe: Any, exclude_job_key: str = "") -> Dict[str, Any]:
        """把 Magnet/ED2K 已提交任务也加入统一 reservation，且排除当前 worker 自己。"""
        base = dict(super()._pending_reservations(subscribe, exclude_job_key=exclude_job_key) or {})
        base["episodes"] = set(base.get("episodes") or set())
        base["paths"] = set(base.get("paths") or set())

        sid = int(getattr(subscribe, "id", 0) or 0)
        current_source_id = self._episode_fence_current_source_v1124()
        store_method = getattr(self, "_source_store", None)
        if sid <= 0 or not callable(store_method):
            return base
        try:
            items = (store_method().get("items") or {}).values()
        except Exception:
            return base

        active_episode_claims: Set[int] = set()
        active_movie = False
        for source in items:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("id") or "")
            if source_id and source_id == current_source_id:
                continue
            if int(source.get("subscribe_id") or 0) != sid:
                continue
            if not bool(source.get("enabled", True)):
                continue
            if str(source.get("state") or "") not in _EXTERNAL_INFLIGHT_V1124:
                continue
            if self._is_movie_subscription(subscribe):
                active_movie = True
                continue
            active_episode_claims.update(self._source_episode_targets_v1124(source))

        if active_episode_claims:
            base["episodes"].update(active_episode_claims)
        if active_movie:
            base["movie"] = True
        return base

    def _mark_uncancellable_source_v1124(
        self,
        source: Dict[str, Any],
        acquired: Set[int],
        reason: str,
    ) -> Dict[str, Any]:
        """服务端取消失败时本地永久停止重试；绝不再创建第二个同集任务。"""
        source_id = str(source.get("id") or "")
        updated = self._update_source(
            source_id,
            state="disabled",
            enabled=False,
            auto_dispatch=False,
            superseded_by_receipt=True,
            superseded_episodes=sorted(acquired),
            superseded_at=self._now_text(),
            superseded_reason=str(reason)[:400],
            remote_cancelled=False,
            next_retry_at=0,
        ) or source
        self._plugin_log(
            "WARNING",
            "【光鸭转存助手】【集级终止】来源 %s 的旧服务端任务无法确认取消；本地已永久停止该来源，绝不再次提交同集任务：%s",
            source_id or "-",
            reason,
        )
        return updated

    def _prepare_offline_source_v1124(
        self,
        source: Dict[str, Any],
        subscribe: Any,
    ) -> Tuple[bool, Dict[str, Any], str]:
        """Magnet/ED2K create/retry/poll 前的最后实时缺集裁剪。"""
        source_id = str(source.get("id") or "")
        targets = self._source_episode_targets_v1124(source)

        if self._is_movie_subscription(subscribe):
            try:
                if self._movie_transfer_confirmed(subscribe):
                    updated = self._disable_offline_source_v1124(
                        source,
                        set(),
                        reason="电影正片已经成功获得",
                    )
                    return False, updated, "电影已完成，停止重复云添加"
            except Exception:
                pass
            return True, source, ""

        if not targets:
            return True, source, ""

        missing = set(self._subscription_missing_episodes(subscribe))
        remaining = targets.intersection(missing)
        superseded = targets - remaining
        if not remaining:
            updated = self._disable_offline_source_v1124(
                source,
                self._acquired_episode_facts_v1124(subscribe),
                reason="该来源目标集均已成功获得",
            )
            return False, updated, "目标集已完成，停止重复云添加"
        if remaining == targets:
            return True, source, ""

        state = str(source.get("state") or "")
        task_id = str(source.get("task_id") or "").strip()
        if task_id:
            # fileIndexes 不能在既有 cloudcollection task 上安全原地修改：必须先取消旧 task。
            if not self._delete_offline_task_v1124(source):
                updated = self._mark_uncancellable_source_v1124(
                    source,
                    superseded,
                    "旧任务同时包含已完成集和未完成集，取消失败；为避免重复入库停止该来源",
                )
                return False, updated, "旧任务无法安全裁剪，已停止以避免重复"
            updated = self._update_source(
                source_id,
                state="new",
                task_id="",
                task_status=0,
                progress=0,
                target_episodes=sorted(remaining),
                resolved_episodes=[],
                selected_indexes=[],
                resolved_url="",
                next_retry_at=0,
                superseded_episodes=sorted(superseded),
                superseded_at=self._now_text(),
                remote_cancelled=True,
            ) or source
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【集级终止】来源 %s 旧 task=%s 已取消；已完成=%s，仅重建剩余=%s",
                source_id or "-",
                task_id,
                ",".join(f"E{value:02d}" for value in sorted(superseded)),
                ",".join(f"E{value:02d}" for value in sorted(remaining)),
            )
            return True, updated, ""

        # 尚未生成服务端 task，可以直接把计划缩成剩余集；同时清除旧 resolve 结果，强制重新选 fileIndexes。
        next_state = "new" if state in {"retry", "dispatching"} else state or "new"
        updated = self._update_source(
            source_id,
            state=next_state,
            target_episodes=sorted(remaining),
            resolved_episodes=[],
            selected_indexes=[],
            resolved_url="",
            next_retry_at=0,
            superseded_episodes=sorted(superseded),
            superseded_at=self._now_text(),
        ) or source
        return True, updated, ""

    def _supersede_offline_sources_v1124(self, subscribe: Any, acquired: Set[int]) -> int:
        """成功回执到达时立即停止/裁剪其它 Magnet/ED2K，而不是等下一轮轮询。"""
        if not acquired:
            return 0
        sid = int(getattr(subscribe, "id", 0) or 0)
        store_method = getattr(self, "_source_store", None)
        if sid <= 0 or not callable(store_method):
            return 0
        try:
            items = list((store_method().get("items") or {}).values())
        except Exception:
            return 0

        affected = 0
        resume_ids: List[str] = []
        for source in items:
            if not isinstance(source, dict) or int(source.get("subscribe_id") or 0) != sid:
                continue
            state = str(source.get("state") or "")
            if state not in _EXTERNAL_ACTIVE_V1124:
                continue
            targets = self._source_episode_targets_v1124(source)
            overlap = targets.intersection(acquired)
            if not overlap:
                continue
            before_task = str(source.get("task_id") or "")
            before_targets = set(targets)
            allowed, updated, _ = self._prepare_offline_source_v1124(source, subscribe)
            affected += 1
            if not allowed:
                continue
            after_targets = self._source_episode_targets_v1124(updated)
            after_task = str(updated.get("task_id") or "")
            changed_plan = after_targets != before_targets or after_task != before_task
            if (
                changed_plan
                and str(updated.get("state") or "") == "new"
                and bool(updated.get("enabled", True))
                and bool(updated.get("auto_dispatch", True))
            ):
                source_id = str(updated.get("id") or "")
                if source_id:
                    resume_ids.append(source_id)

        # worker 会在当前媒体 RLock 释放后才真正提交，因此一定能读到刚写入的最新缺集事实。
        for source_id in dict.fromkeys(resume_ids):
            try:
                self._spawn_source_dispatch(source_id)
            except Exception as err:
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【集级终止】剩余集任务 %s 自动续跑失败，等待下一轮：%s",
                    source_id,
                    str(err)[:260],
                )
        return affected

    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        """记录当前 worker 身份，让统一 reservation 只排除自己、不排除其它在途来源。"""
        context = getattr(self, "_episode_fence_context_v1124", None)
        if context is None:
            self._episode_fence_context_v1124 = threading.local()
            context = self._episode_fence_context_v1124
        previous = str(getattr(context, "source_id", "") or "")
        context.source_id = str(source_id or "")
        try:
            return super()._submit_offline_source(source_id)
        finally:
            context.source_id = previous

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """轮询前实时裁剪，并确保取消重建后绝不再拿旧 task_id 去 poll。"""
        source_id = str(source.get("id") or "")
        latest = dict((self._source_store().get("items") or {}).get(source_id) or source)
        subscribe = self._find_subscription(int(latest.get("subscribe_id") or 0))
        if not subscribe:
            return super()._poll_offline_source(latest)

        context = getattr(self, "_episode_fence_context_v1124", None)
        if context is None:
            self._episode_fence_context_v1124 = threading.local()
            context = self._episode_fence_context_v1124
        previous = str(getattr(context, "source_id", "") or "")
        context.source_id = source_id
        try:
            lock = self._episode_fence_lock_v1124(subscribe)
            with lock:
                latest = dict((self._source_store().get("items") or {}).get(source_id) or latest)
                fresh = self._find_subscription(int(latest.get("subscribe_id") or 0)) or subscribe
                allowed, prepared, message = self._prepare_offline_source_v1124(latest, fresh)
                if not allowed:
                    return {"success": True, "handled": True, "message": message, "data": prepared}
                if not str(prepared.get("task_id") or "").strip():
                    # 旧 task 已因部分重叠被取消；不要 poll 旧 ID。退出本次 poll，由新 worker/下一轮按剩余集 create。
                    if str(prepared.get("state") or "") == "new" and bool(prepared.get("auto_dispatch", True)):
                        self._spawn_source_dispatch(source_id)
                    return {
                        "success": True,
                        "handled": True,
                        "message": "旧重复任务已终止，仅剩余缺集待重新提交",
                        "data": prepared,
                    }
                # 跳过 episode_fence_v1124 的旧 poll 包装，直接进入其后的正常完成回执链。
                return super(GuangYaEpisodeFenceV1124Mixin, self)._poll_offline_source(prepared)
        finally:
            context.source_id = previous

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        """电影若已有其它来源在途则不再抢跑第二份正片；TV 的在途集由 planner reservation 处理。"""
        if self._is_movie_subscription(subscribe):
            pending = dict(self._pending_reservations(subscribe) or {})
            if bool(pending.get("movie")):
                try:
                    completed = bool(self._movie_transfer_confirmed(subscribe))
                except Exception:
                    completed = False
                return {
                    "success": completed,
                    "handled": completed,
                    "shares": 0,
                    "attempted_files": 0,
                    "successful_files": 0,
                    "episodes": [],
                    "movie": completed,
                    "message": "电影已有成功/在途获取任务，跳过重复迅雷秒传" if not completed else "电影已成功获得，跳过重复迅雷秒传",
                }
        return super()._dispatch_xunlei_flash(subscribe)


__all__ = ["GuangYaEpisodeFenceFinalV1124Mixin"]
