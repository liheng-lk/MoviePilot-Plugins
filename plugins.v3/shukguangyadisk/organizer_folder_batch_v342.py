"""光鸭自动整理 v3.4.2：真正的“一个资源文件夹 = 一个整理任务”。

v3.4.0/v3.4.1 虽然按目录扫描和记录批次，但最终仍把每个文件分别提交给私有 worker，
因此 MoviePilot 会反复显示“正在计划整理 1 个文件 / 开始整理，共 1 个文件”。

本补丁把监控根下的直接子目录作为私有队列任务：

    folder scan -> one folder envelope -> isolated worker ->
    TransferChain.do_transfer(directory, background=False)

MoviePilot 会自行递归目录、一次规划该目录内全部候选文件，并在同一次整理调用中逐个处理。
插件仍保留逐文件状态、历史预检、失败重试和最终事件回写。

对于插件专门兼容的弱命名（例如 ``22~[4K]...``），MoviePilot 直接扫描目录时无法获得
插件逐文件构造的季集上下文，因此仍在“同一个文件夹私有任务”内部逐文件执行，避免
识别能力回退。监控根直接散放文件也使用该兼容模式，防止把整个监控根递归成一个任务。
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.chain.transfer import TransferChain
from app.schemas.workflow import FileItem
from app.sdk.logging import logger

from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_state import OrganizerStateStore


_WEAK_EPISODE_NAME = re.compile(r"^\s*\d{1,3}\s*[~～]", re.IGNORECASE)


@dataclass
class _FolderBatchEnvelope:
    """只存在于插件私有内存队列中的文件夹任务。"""

    path: str
    name: str
    members: List[Any]
    batch_id: str
    directory_mode: bool
    fileid: str
    size: int
    modify_time: float
    type: str = "dir"



def _batch_fingerprint(plugin: Any, members: List[Any], group_path: str) -> str:
    raw = [group_path]
    for member in members:
        raw.append(plugin._fingerprint(member))
    return hashlib.sha1("|".join(raw).encode("utf-8")).hexdigest()



def _can_use_native_directory_batch(plugin: Any, group_path: str, members: List[Any]) -> bool:
    """判断能否直接把整个目录交给 MoviePilot。

    监控根散放文件不能把根目录交给 MP，否则会把所有子目录一起递归；弱数字集号则需要
    插件现有的逐文件上下文桥，因此也回退为同一 folder task 内逐文件执行。
    """
    if plugin._organize_normalize_path(group_path) == plugin._organize_normalize_path(
        plugin._organize_monitor_path
    ):
        return False

    for member in members:
        path = Path(str(getattr(member, "path", "") or ""))
        if _WEAK_EPISODE_NAME.match(path.name):
            return False
        parser = getattr(plugin, "_explicit_episode_context", None)
        if callable(parser):
            try:
                context = parser(path)
            except Exception:
                context = None
            if context and len(context) >= 4 and str(context[3]) == "父目录 + 数字集号":
                return False
    return True



def _patched_process_folder_group(
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
    """完整目录作为一个私有队列任务提交，而不是逐文件创建 worker 任务。"""
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
        "folder_tasks": 0,
    }

    now = time.time()
    ready: List[Tuple[Any, str, str]] = []
    hard_wait = False

    for item in files:
        path = self._organize_normalize_path(getattr(item, "path", ""))
        fp = self._fingerprint(item)
        event_path = Path(path)

        if not dispatcher.is_transfer_candidate_path(event_path):
            counters["unsupported"] += 1
            state.mark_ignored(path=path, fingerprint=fp)
            continue

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
            hard_wait = True
        elif phase == "inflight":
            counters["inflight"] += 1
            # 同一个目录已有成员处于执行/等待状态时，绝不再创建第二个目录任务。
            hard_wait = True
        elif phase == "retry_wait":
            counters["retry_wait"] += 1
        elif phase == "ready":
            ready.append((item, path, fp))

    counters["ready"] = len(ready)
    if not ready:
        return counters

    submit_items: List[Tuple[Any, str, str, Any]] = []
    for item, path, fp in ready:
        preflight = self._preflight_history(item, path)
        decision = str(preflight.get("decision") or "unknown")
        message = str(preflight.get("message") or "")

        if decision == "completed":
            counters["history_completed"] += 1
            state.mark_completed(path=path, fingerprint=fp)
            continue
        if decision == "blocked":
            counters["newly_blocked"] += 1
            state.mark_blocked(
                path=path,
                fingerprint=fp,
                reason=message,
                now=time.time(),
            )
            continue
        if decision == "unknown":
            counters["deferred"] += 1
            state.mark_deferred(
                path=path,
                fingerprint=fp,
                now=time.time(),
                reason=message or "MoviePilot 整理历史暂不可用",
            )
            # history 暂不可用时不能把目录整体交给 MP，否则会绕过保守等待。
            hard_wait = True
            continue

        submit_items.append((item, path, fp, preflight.get("action")))

    if not submit_items:
        return counters

    # 同目录仍有正在写入/执行/历史未知的文件时，整个资源目录保持“等待整理”。
    # 这样不会出现同一个文件夹被拆成多个互相独立的 worker 批次。
    if hard_wait:
        counters["capacity_wait"] += len(submit_items)
        return counters

    remaining = int(submit_budget.get("remaining") or 0)
    member_count = len(submit_items)
    if remaining <= 0:
        counters["capacity_wait"] += member_count
        return counters

    # 不拆文件夹。容量不足时整个目录等下一次低水位补充；若它本身就大于 batch_size，
    # 且当前没有其它 inflight，则允许这个超大目录独占本轮。
    if member_count > remaining and remaining != self._organize_monitor_batch_size:
        counters["capacity_wait"] += member_count
        return counters

    batch_id = self._new_group_batch_id(group_path, scan_started)
    self._organize_active_group_path = group_path
    self._organize_active_batch_id = batch_id

    attempts: Dict[str, int] = {}
    accepted_members: List[Any] = []
    try:
        for item, path, fp, history_action in submit_items:
            attempt = state.mark_submitting(
                path=path,
                fingerprint=fp,
                now=time.time(),
                metadata={
                    "name": str(getattr(item, "name", "") or Path(path).name),
                    "size": int(getattr(item, "size", 0) or 0),
                    "history_action": history_action,
                    "group_path": group_path,
                    "group_name": self._group_name(group_path),
                    "batch_id": batch_id,
                    "folder_task": True,
                },
            )
            if attempt:
                attempts[path] = attempt
                accepted_members.append(item)

        if not accepted_members:
            return counters

        directory_mode = _can_use_native_directory_batch(self, group_path, accepted_members)
        envelope = _FolderBatchEnvelope(
            path=group_path,
            name=self._group_name(group_path),
            members=accepted_members,
            batch_id=batch_id,
            directory_mode=directory_mode,
            fileid=_batch_fingerprint(self, accepted_members, group_path),
            size=sum(int(getattr(item, "size", 0) or 0) for item in accepted_members),
            modify_time=max(
                [float(getattr(item, "modify_time", 0) or 0) for item in accepted_members] or [0.0]
            ),
        )

        try:
            accepted = self._dispatch_to_moviepilot(envelope)
        except Exception as err:  # noqa: BLE001
            accepted = False
            dispatch_error = str(err)
        else:
            dispatch_error = ""

        if accepted:
            counters["submitted"] += len(accepted_members)
            counters["folder_tasks"] += 1
            submit_budget["remaining"] = max(remaining - len(accepted_members), 0)
            mode_text = "MoviePilot 原生目录批量" if directory_mode else "弱命名兼容批量"
            self._append_monitor_history({
                "time": now_text,
                "path": group_path,
                "name": self._group_name(group_path),
                "size": envelope.size,
                "result": "folder_queued",
                "group_path": group_path,
                "group_name": self._group_name(group_path),
                "batch_id": batch_id,
                "message": (
                    f"文件夹任务已进入私有 worker：{len(accepted_members)} 个待整理文件；"
                    f"模式={mode_text}"
                ),
            })
            logger.info(
                "【光鸭云盘助手】【文件夹任务】已入队: %s，成员=%s，模式=%s",
                group_path,
                len(accepted_members),
                mode_text,
            )
        else:
            counters["deferred"] += len(accepted_members)
            reason = dispatch_error or "私有 worker 当前未接收文件夹任务"
            for item, path, fp, _ in submit_items:
                if path not in attempts:
                    continue
                state.mark_deferred(
                    path=path,
                    fingerprint=fp,
                    now=time.time(),
                    reason=reason,
                )
            logger.warning(
                "【光鸭云盘助手】【文件夹任务】入队失败，成员回到重试: %s - %s",
                group_path,
                reason,
            )
    finally:
        self._organize_active_group_path = ""
        self._organize_active_batch_id = ""

    return counters



def _install_queue_batch_execution() -> None:
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_folder_batch_v342", False):
        return

    original_execute = GuangYaQueueRecoveryMixin._execute_isolated_transfer
    original_fallback = GuangYaQueueRecoveryMixin._fallback_terminal_state

    def execute(self, item: Any):
        if not isinstance(item, _FolderBatchEnvelope):
            return original_execute(self, item)

        if not item.directory_mode:
            # 弱命名仍保持一个“文件夹私有任务”，但内部复用已验证的逐文件上下文桥。
            all_success = True
            messages: List[str] = []
            logger.info(
                "【光鸭云盘助手】【文件夹任务】【兼容模式】开始: %s，共 %s 个文件",
                item.path,
                len(item.members),
            )
            for member in item.members:
                success, message = original_execute(self, member)
                # 动态分派到最终插件实例，让 admission conflict guard 先于旧 retry fallback 生效。
                self._fallback_terminal_state(member, success=success, message=message)
                all_success = all_success and bool(success)
                if message:
                    messages.append(str(message))
            return all_success, "；".join(messages[:3])

        directory_item = FileItem(
            storage=self._disk_name,
            path=self._organize_normalize_path(item.path),
            type="dir",
            name=item.name,
            basename=item.name,
            extension="",
            size=item.size,
            modify_time=item.modify_time,
            fileid=None,
        )
        logger.info(
            "【光鸭云盘助手】【文件夹任务】【原生目录批量】开始: %s，待整理成员=%s；"
            "由 MoviePilot 一次规划整个目录",
            item.path,
            len(item.members),
        )
        result = TransferChain().do_transfer(
            fileitem=directory_item,
            background=False,
            manual=False,
        )
        if isinstance(result, tuple):
            success = bool(result[0])
            message = result[1]
        else:
            success = bool(result)
            message = ""
        if isinstance(message, dict):
            message = str(message.get("message") or message)
        return success, str(message or "")

    def fallback(self, item: Any, success: bool, message: str) -> None:
        if not isinstance(item, _FolderBatchEnvelope):
            return original_fallback(self, item, success=success, message=message)

        # 正常情况下目录整理会逐文件发送 TransferComplete/TransferFailed，成员状态已经收敛。
        # 这里只处理仍留在 inflight 的成员，防止某个宿主小版本漏发最终事件后永久卡住。
        for member in item.members:
            original_fallback(self, member, success=success, message=message)

        self._append_monitor_history({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": item.path,
            "name": item.name,
            "size": item.size,
            "result": "folder_completed" if success else "folder_failed",
            "group_path": item.path,
            "group_name": item.name,
            "batch_id": item.batch_id,
            "message": (
                f"文件夹任务结束：成员 {len(item.members)}，"
                f"{'MoviePilot 原生目录批量' if item.directory_mode else '弱命名兼容批量'}"
                + (f"；{message}" if message else "")
            ),
        })

    GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute
    GuangYaQueueRecoveryMixin._fallback_terminal_state = fallback
    GuangYaQueueRecoveryMixin._guangya_folder_batch_v342 = True



def _install_save_without_forced_rescan() -> None:
    if getattr(_BaseOrganizerMixin, "_guangya_save_no_rescan_v342", False):
        return

    original_save = _BaseOrganizerMixin.api_organize_monitor_save

    def save(self, payload: dict):
        old_tick = float(getattr(self, "_organize_monitor_last_tick", 0.0) or 0.0)
        old_enabled = bool(getattr(self, "_organize_monitor_enabled", False))
        old_path = str(getattr(self, "_organize_monitor_path", "") or "")
        response = original_save(self, payload)
        if isinstance(response, dict) and response.get("success"):
            new_enabled = bool(getattr(self, "_organize_monitor_enabled", False))
            new_path = str(getattr(self, "_organize_monitor_path", "") or "")
            # 保存同一监控目录的参数不等于“开始下一批扫描”。保留原发现周期，
            # 当前文件夹任务由同一私有 worker 自己跑完。
            if old_enabled and new_enabled and old_path == new_path:
                self._organize_monitor_last_tick = old_tick
                self._save_monitor_status(
                    config_save_forced_rescan=False,
                    folder_task_mode="one_folder_one_task",
                )
        return response

    _BaseOrganizerMixin.api_organize_monitor_save = save
    _BaseOrganizerMixin._guangya_save_no_rescan_v342 = True



def install_folder_batch_v342() -> None:
    """安装 v3.4.2 文件夹任务补丁；重复导入安全。"""
    if not getattr(GuangYaFolderStreamMixin, "_guangya_folder_batch_v342", False):
        GuangYaFolderStreamMixin._process_folder_group = _patched_process_folder_group
        GuangYaFolderStreamMixin._guangya_folder_batch_v342 = True
    _install_queue_batch_execution()
    _install_save_without_forced_rescan()


__all__ = ["install_folder_batch_v342"]
