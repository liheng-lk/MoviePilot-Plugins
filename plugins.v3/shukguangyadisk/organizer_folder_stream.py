"""光鸭云盘自动整理的“子目录流式批次”调度层。

设计目标：
1. 不再等待整个监控树扫描完才开始整理；一个直接子目录完整扫描后即可立即把该目录
   中已满足稳定性和 MoviePilot 门控的文件连续提交给 MP。
2. 一个子目录作为一个可观测批次，队列与历史记录均携带 group_path/group_name，
   便于电视剧整季、短剧全集和电影发布目录统一查看。
3. 批次提交仍受现有 batch_size 约束；若一个目录超过剩余预算，则优先续完当前目录，
   后续目录只扫描建库存，不抢占本轮提交预算。
4. 只有完整遍历结束后才执行 inventory reconciliation；扫描截断或异常不会因为部分
   inventory 而删除已有状态。

媒体识别、分类、目标目录、重命名、整理方式、覆盖和刮削仍由
``organizer_recognition.GuangYaOrganizerMixin`` 与 MoviePilot 原生整理链负责。
"""

from __future__ import annotations

import datetime
import hashlib
import time
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, List, Tuple

from app.sdk.logging import logger

from .organizer_state import OrganizerStateStore


class GuangYaFolderStreamMixin:
    """把全树“扫描后提交”改为“完整子目录扫描后立即提交”的调度覆盖层。"""

    _organize_scan_mode = "folder_stream"
    _organize_active_group_path: str = ""
    _organize_active_batch_id: str = ""

    def _group_path_for_file(self, value: Any) -> str:
        """返回文件所属的监控根直接子目录；根目录直放文件归入监控根批次。"""
        path = PurePosixPath(self._organize_normalize_path(value))
        root = PurePosixPath(self._organize_monitor_path)
        try:
            relative = path.relative_to(root)
        except ValueError:
            return self._organize_normalize_path(str(path.parent))
        if len(relative.parts) <= 1:
            return self._organize_normalize_path(str(root))
        return self._organize_normalize_path(str(root / relative.parts[0]))

    @staticmethod
    def _group_name(group_path: str) -> str:
        path = PurePosixPath(group_path)
        return path.name or "/"

    @staticmethod
    def _group_sort_key(item: Any) -> Tuple[float, str]:
        return (
            float(getattr(item, "modify_time", 0) or 0),
            str(getattr(item, "name", "") or "").casefold(),
        )

    @staticmethod
    def _file_sort_key(item: Any) -> Tuple[float, str]:
        return (
            float(getattr(item, "modify_time", 0) or 0),
            str(getattr(item, "path", "") or "").casefold(),
        )

    def _new_group_batch_id(self, group_path: str, started_at: float) -> str:
        raw = f"{group_path}|{started_at:.6f}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _append_monitor_history(self, row: Dict[str, Any]) -> None:
        """在不改变旧 UI 字段的前提下，为每条流水补充子目录分组信息。"""
        enriched = dict(row or {})
        raw_path = str(enriched.get("path") or "")
        group_path = str(enriched.get("group_path") or "")
        if not group_path and raw_path:
            group_path = self._group_path_for_file(raw_path)
        if group_path:
            enriched.setdefault("group_path", group_path)
            enriched.setdefault("group_name", self._group_name(group_path))
        if (
            self._organize_active_batch_id
            and group_path
            and group_path == self._organize_active_group_path
        ):
            enriched.setdefault("batch_id", self._organize_active_batch_id)
        return super()._append_monitor_history(enriched)

    def _iter_folder_groups(
        self,
        root_path: str,
        scan_meta: Dict[str, Any],
    ) -> Iterator[Tuple[str, List[Any]]]:
        """逐个完整产生“监控根直接子目录”批次。

        ``scan_meta`` 是调用方持有的可变扫描账本。达到 inventory cap 时停止继续产生批次，
        并设置 ``truncated=True``；当前未完整扫描的目录不会被提交。
        """
        if not self._guangya_api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")

        normalized_root = self._organize_normalize_path(root_path)
        root = self._guangya_api.get_item(Path(normalized_root))
        if not root or root.type != "dir":
            raise RuntimeError(f"监控目录不存在: {normalized_root}")

        scan_meta.setdefault("inventory_paths", set())
        scan_meta.setdefault("visited", 0)
        scan_meta.setdefault("files", 0)
        scan_meta.setdefault("groups_discovered", 0)
        scan_meta.setdefault("groups_scanned", 0)
        scan_meta.setdefault("truncated", False)

        def account(child: Any) -> bool:
            scan_meta["visited"] += 1
            if scan_meta["visited"] > self._monitor_inventory_cap:
                scan_meta["truncated"] = True
                return False
            return True

        root_files: List[Any] = []
        child_dirs: List[Any] = []
        for child in self._guangya_api.list(root) or []:
            if not account(child):
                return
            if str(getattr(child, "name", "") or "").startswith("."):
                continue
            if child.type == "dir":
                if self._organize_monitor_recursive:
                    child_dirs.append(child)
            elif child.type == "file":
                root_files.append(child)
                path = self._organize_normalize_path(getattr(child, "path", ""))
                scan_meta["inventory_paths"].add(path)
                scan_meta["files"] += 1

        if root_files:
            scan_meta["groups_discovered"] += 1
            scan_meta["groups_scanned"] += 1
            root_files.sort(key=self._file_sort_key)
            yield normalized_root, root_files

        if not self._organize_monitor_recursive:
            return

        child_dirs.sort(key=self._group_sort_key)
        scan_meta["groups_discovered"] += len(child_dirs)

        for group_dir in child_dirs:
            group_path = self._organize_normalize_path(getattr(group_dir, "path", ""))
            group_files: List[Any] = []
            queue = deque([group_dir])
            group_complete = True

            while queue:
                current = queue.popleft()
                for child in self._guangya_api.list(current) or []:
                    if not account(child):
                        group_complete = False
                        queue.clear()
                        break
                    if str(getattr(child, "name", "") or "").startswith("."):
                        continue
                    if child.type == "dir":
                        queue.append(child)
                    elif child.type == "file":
                        group_files.append(child)
                        path = self._organize_normalize_path(getattr(child, "path", ""))
                        scan_meta["inventory_paths"].add(path)
                        scan_meta["files"] += 1
                if not group_complete:
                    break

            if not group_complete:
                logger.warning(
                    "【光鸭云盘助手】【自动整理】【目录批次】扫描达到 inventory cap，"
                    "当前目录不提交，保留已有状态: %s",
                    group_path,
                )
                return

            scan_meta["groups_scanned"] += 1
            group_files.sort(key=self._file_sort_key)
            yield group_path, group_files

    def _process_folder_group(
        self,
        *,
        group_path: str,
        files: List[Any],
        dispatcher: Any,
        state: OrganizerStateStore,
        submit_budget: Dict[str, int],
        now_text: str,
        scan_started: float,
    ) -> Dict[str, int]:
        """完整评估一个目录，并把 ready 文件连续提交到 MP，直到预算用尽。"""
        counters = {
            "files": len(files),
            "changed": 0,
            "waiting": 0,
            "inflight": 0,
            "retry_wait": 0,
            "completed": 0,
            "ignored": 0,
            "blocked": 0,
            "ready": 0,
            "submitted": 0,
            "deferred": 0,
            "failed": 0,
            "unsupported": 0,
            "history_completed": 0,
            "newly_blocked": 0,
            "capacity_wait": 0,
        }

        now = time.time()
        ready: List[Tuple[Any, str, str]] = []
        for item in files:
            path = self._organize_normalize_path(getattr(item, "path", ""))
            fp = self._fingerprint(item)
            phase = state.classify(
                path=path,
                fingerprint=fp,
                now=now,
                stability_seconds=self._organize_monitor_stability,
                inflight_lease_seconds=self._monitor_inflight_lease,
            )
            if phase == "completed":
                counters["completed"] += 1
                continue
            if phase == "ignored":
                counters["ignored"] += 1
                continue
            if phase == "blocked":
                counters["blocked"] += 1
                continue

            counters["changed"] += 1
            if phase == "stabilizing":
                counters["waiting"] += 1
            elif phase == "inflight":
                counters["inflight"] += 1
            elif phase == "retry_wait":
                counters["retry_wait"] += 1
            elif phase == "ready":
                ready.append((item, path, fp))

        counters["ready"] = len(ready)
        batch_id = self._new_group_batch_id(group_path, scan_started)
        self._organize_active_group_path = group_path
        self._organize_active_batch_id = batch_id

        try:
            for item, path, fp in ready:
                if submit_budget["remaining"] <= 0:
                    counters["capacity_wait"] += 1
                    continue

                event_path = Path(path)
                if not dispatcher.is_transfer_candidate_path(event_path):
                    counters["unsupported"] += 1
                    state.mark_ignored(path=path, fingerprint=fp)
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="ignored",
                        message="MoviePilot 当前媒体/字幕/音频扩展名规则不处理该文件",
                    ))
                    continue

                preflight = self._preflight_history(item, path)
                decision = str(preflight.get("decision") or "unknown")
                preflight_message = str(preflight.get("message") or "")
                if decision == "completed":
                    counters["history_completed"] += 1
                    state.mark_completed(path=path, fingerprint=fp)
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="history_completed",
                        message=preflight_message,
                    ))
                    continue
                if decision == "blocked":
                    counters["newly_blocked"] += 1
                    state.mark_blocked(
                        path=path,
                        fingerprint=fp,
                        reason=preflight_message,
                        now=time.time(),
                    )
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="blocked",
                        message=f"{preflight_message}；10 分钟后自动重新检查，也可手动解除等待",
                    ))
                    continue
                if decision == "unknown":
                    counters["deferred"] += 1
                    retry = state.mark_deferred(
                        path=path,
                        fingerprint=fp,
                        now=time.time(),
                        reason=preflight_message or "MoviePilot 整理历史暂不可用",
                    )
                    self._append_monitor_history(self._history_row(
                        now_text=now_text,
                        item=item,
                        path=path,
                        result="deferred",
                        message=f"{preflight_message}；{int(retry.get('delay') or 0)} 秒后重试",
                    ))
                    continue

                attempts = state.mark_submitting(
                    path=path,
                    fingerprint=fp,
                    now=time.time(),
                    metadata={
                        "name": str(getattr(item, "name", "") or Path(path).name),
                        "size": int(getattr(item, "size", 0) or 0),
                        "history_action": preflight.get("action"),
                        "group_path": group_path,
                        "group_name": self._group_name(group_path),
                        "batch_id": batch_id,
                    },
                )
                if attempts == 0:
                    continue

                try:
                    accepted = self._dispatch_to_moviepilot(item)
                    if accepted:
                        counters["submitted"] += 1
                        submit_budget["remaining"] -= 1
                        self._append_monitor_history(self._history_row(
                            now_text=now_text,
                            item=item,
                            path=path,
                            result="queued",
                            message=(
                                f"子目录批次 {self._group_name(group_path)} 已进入 MoviePilot 整理链，"
                                f"等待最终回执（第 {attempts} 次）"
                            ),
                        ))
                    else:
                        counters["deferred"] += 1
                        retry = state.mark_deferred(
                            path=path,
                            fingerprint=fp,
                            now=time.time(),
                            reason="MoviePilot 预检允许提交，但当前未接收入队：可能为 TTL 去重或并发门控",
                        )
                        self._append_monitor_history(self._history_row(
                            now_text=now_text,
                            item=item,
                            path=path,
                            result="deferred",
                            message=f"MoviePilot 暂未接收入队，{int(retry.get('delay') or 0)} 秒后自动重试",
                        ))
                except Exception as err:  # noqa: BLE001 - translate to persistent retry state
                    counters["failed"] += 1
                    retry = state.mark_failed(
                        path=path,
                        fingerprint=fp,
                        now=time.time(),
                        reason=str(err),
                    )
                    logger.error(
                        "【光鸭云盘助手】【自动整理】【目录批次】提交 MP 失败: %s - %s；%s 秒后重试",
                        path,
                        err,
                        int(retry.get("delay") or 0),
                    )

            if any(counters[key] for key in (
                "submitted",
                "ready",
                "history_completed",
                "newly_blocked",
                "failed",
            )):
                summary = {
                    "time": now_text,
                    "path": group_path,
                    "name": self._group_name(group_path),
                    "size": 0,
                    "result": "folder_batch",
                    "group_path": group_path,
                    "group_name": self._group_name(group_path),
                    "batch_id": batch_id,
                    "message": (
                        f"目录批次：文件 {len(files)}，可提交 {counters['ready']}，"
                        f"本轮入队 {counters['submitted']}，等待容量 {counters['capacity_wait']}，"
                        f"历史完成 {counters['history_completed']}，重试/门控 "
                        f"{counters['deferred'] + counters['newly_blocked']}"
                    ),
                }
                self._append_monitor_history(summary)
        finally:
            self._organize_active_group_path = ""
            self._organize_active_batch_id = ""

        return counters

    @staticmethod
    def _merge_counters(total: Dict[str, int], part: Dict[str, int]) -> None:
        for key, value in part.items():
            total[key] = int(total.get(key, 0) or 0) + int(value or 0)

    def run_organize_monitor_scan(self, manual: bool = False) -> Dict[str, Any]:
        """逐子目录扫描并即时入队；扫描与 MoviePilot 整理可以重叠执行。"""
        self.init_organizer_monitor()
        if not manual and not self._organize_monitor_enabled:
            return {"success": True, "message": "自动整理监控未启用", "data": {"disabled": True}}
        if not self._enabled or not self._guangya_api:
            return {"success": False, "message": "光鸭云盘未启用或未登录"}
        if self._organize_monitor_path == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止直接监控根目录"}

        lock = self._organize_scan_lock
        if lock is None:
            import threading
            lock = threading.Lock()
            self._organize_scan_lock = lock
        if not lock.acquire(blocking=False):
            return {"success": False, "message": "已有自动整理扫描正在运行，请稍后再试"}

        started = time.time()
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        scan_meta: Dict[str, Any] = {
            "inventory_paths": set(),
            "visited": 0,
            "files": 0,
            "groups_discovered": 0,
            "groups_scanned": 0,
            "groups_queued": 0,
            "truncated": False,
        }
        totals: Dict[str, int] = {}

        try:
            dispatcher = self._get_organize_dispatcher()
            try:
                dispatcher.retry_pending()
            except Exception as err:
                logger.debug("【光鸭云盘助手】【自动整理】MP 待重试检查失败: %s", err)

            state = self._state()
            existing_inflight = int(state.stats().get("inflight") or 0)
            # batch_size 在 v3.4.0 中同时作为单轮新增任务预算与 MP 待整理背压上限。
            submit_budget = {
                "remaining": max(self._organize_monitor_batch_size - existing_inflight, 0)
            }

            self._save_monitor_status(
                running=self._organize_monitor_enabled,
                scan_in_progress=True,
                scan_mode=self._organize_scan_mode,
                scan_started=now_text,
                monitor_path=self._organize_monitor_path,
                current_group="",
                groups_discovered=0,
                groups_scanned=0,
                groups_queued=0,
                submitted=0,
                queue_limit=self._organize_monitor_batch_size,
                queue_slots=submit_budget["remaining"],
                errors=[],
            )

            for group_path, files in self._iter_folder_groups(self._organize_monitor_path, scan_meta):
                group_result = self._process_folder_group(
                    group_path=group_path,
                    files=files,
                    dispatcher=dispatcher,
                    state=state,
                    submit_budget=submit_budget,
                    now_text=now_text,
                    scan_started=started,
                )
                self._merge_counters(totals, group_result)
                if group_result.get("submitted"):
                    scan_meta["groups_queued"] += 1

                state_counts = state.stats()
                self._save_monitor_status(
                    running=self._organize_monitor_enabled,
                    scan_in_progress=True,
                    scan_mode=self._organize_scan_mode,
                    scan_started=now_text,
                    monitor_path=self._organize_monitor_path,
                    current_group=group_path,
                    current_group_name=self._group_name(group_path),
                    current_group_files=len(files),
                    current_group_submitted=group_result.get("submitted", 0),
                    groups_discovered=scan_meta["groups_discovered"],
                    groups_scanned=scan_meta["groups_scanned"],
                    groups_queued=scan_meta["groups_queued"],
                    inventory=scan_meta["files"],
                    submitted=totals.get("submitted", 0),
                    inflight=state_counts.get("inflight", 0),
                    completed=state_counts.get("completed", 0),
                    retry_wait=state_counts.get("retry_wait", 0),
                    blocked=state_counts.get("blocked", 0),
                    queue_limit=self._organize_monitor_batch_size,
                    queue_slots=submit_budget["remaining"],
                    truncated=scan_meta["truncated"],
                )

            # 只有整个扫描器正常走到这里才做 inventory reconciliation；truncated=True 时
            # OrganizerStateStore 自身也会拒绝删除任何未出现状态。
            state.reconcile_inventory(
                scan_meta["inventory_paths"],
                truncated=bool(scan_meta["truncated"]),
            )
            state.set_metadata(monitor_path=self._organize_monitor_path, updated_at=now_text)
            state_counts = state.stats()

            status = self._save_monitor_status(
                running=self._organize_monitor_enabled,
                scan_in_progress=False,
                scan_mode=self._organize_scan_mode,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                current_group="",
                inventory=scan_meta["files"],
                changed=totals.get("changed", 0),
                waiting=totals.get("waiting", 0),
                inflight=state_counts.get("inflight", 0),
                retry_wait=state_counts.get("retry_wait", 0),
                completed=state_counts.get("completed", 0),
                ignored=state_counts.get("ignored", 0),
                blocked=state_counts.get("blocked", 0),
                submitted=totals.get("submitted", 0),
                history_completed=totals.get("history_completed", 0),
                deferred=totals.get("deferred", 0),
                unsupported=totals.get("unsupported", 0),
                newly_blocked=totals.get("newly_blocked", 0),
                failed=totals.get("failed", 0),
                capacity_wait=totals.get("capacity_wait", 0),
                groups_discovered=scan_meta["groups_discovered"],
                groups_scanned=scan_meta["groups_scanned"],
                groups_queued=scan_meta["groups_queued"],
                queue_limit=self._organize_monitor_batch_size,
                queue_slots=submit_budget["remaining"],
                truncated=scan_meta["truncated"],
                duration_ms=int((time.time() - started) * 1000),
                errors=[],
                state_schema=OrganizerStateStore.schema_version,
            )
            message = (
                f"目录流式扫描完成：子目录 {scan_meta['groups_scanned']}/{scan_meta['groups_discovered']}，"
                f"文件 {scan_meta['files']}，提交 MP {totals.get('submitted', 0)}，"
                f"整理中 {state_counts.get('inflight', 0)}，等待容量 {totals.get('capacity_wait', 0)}，"
                f"重试等待 {state_counts.get('retry_wait', 0)}，MP 门控 {state_counts.get('blocked', 0)}"
            )
            logger.info("【光鸭云盘助手】【自动整理】【目录流式】%s", message)
            return {
                "success": not bool(totals.get("failed", 0)),
                "message": message,
                "data": status,
            }
        except Exception as err:  # noqa: BLE001 - partial scan must preserve already queued work
            logger.exception("【光鸭云盘助手】【自动整理】【目录流式】扫描失败: %s", err)
            # 这里故意不 reconcile_inventory：此前已经完成的目录批次可以继续由 MP 整理，
            # 但不允许用不完整 inventory 清除未扫描目录的持久状态。
            status = self._save_monitor_status(
                running=self._organize_monitor_enabled,
                scan_in_progress=False,
                scan_mode=self._organize_scan_mode,
                last_scan=now_text,
                monitor_path=self._organize_monitor_path,
                current_group=self._organize_active_group_path,
                inventory=scan_meta.get("files", 0),
                groups_discovered=scan_meta.get("groups_discovered", 0),
                groups_scanned=scan_meta.get("groups_scanned", 0),
                groups_queued=scan_meta.get("groups_queued", 0),
                submitted=totals.get("submitted", 0),
                failed=int(totals.get("failed", 0) or 0) + 1,
                partial=True,
                errors=[str(err)],
                duration_ms=int((time.time() - started) * 1000),
            )
            return {
                "success": False,
                "message": f"目录流式扫描部分失败，已提交批次继续整理且未清理未扫描状态: {err}",
                "data": status,
            }
        finally:
            self._organize_active_group_path = ""
            self._organize_active_batch_id = ""
            lock.release()


__all__ = ["GuangYaFolderStreamMixin"]
