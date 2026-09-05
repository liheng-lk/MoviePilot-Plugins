"""115 离线任务状态恢复。

只处理已经提交到 115 的 Magnet/ED2K。找不到远端任务时保持原状态等待下一轮，
绝不把一次列表缺失当作失败；只有远端明确失败状态才释放 Episode Fence。
"""

from __future__ import annotations

from time import time
from typing import Any, Dict, List, Optional

from .dispatcher import TransferDispatcher
from .models import SourceType, TaskState, TransferTask
from .p115_provider import P115TransferProvider
from .task_store import TaskStore


class TransferRecovery:
    COMPLETE_CODES = {11}
    FAILED_CODES = {9}

    def __init__(self, provider: P115TransferProvider, store: TaskStore, dispatcher: TransferDispatcher):
        self.provider = provider
        self.store = store
        self.dispatcher = dispatcher

    @staticmethod
    def _records(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Any] = [resp.get("data"), resp.get("tasks"), resp.get("list")]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if isinstance(candidate, dict):
                for key in ("tasks", "list", "data"):
                    value = candidate.get(key)
                    if isinstance(value, list):
                        return [item for item in value if isinstance(item, dict)]
                if any(key in candidate for key in ("info_hash", "hash", "status", "stat", "url")):
                    return [candidate]
        return []

    @staticmethod
    def _record_hash(record: Dict[str, Any]) -> str:
        return str(
            record.get("info_hash")
            or record.get("infoHash")
            or record.get("hash")
            or record.get("task_id")
            or record.get("taskId")
            or ""
        ).strip().lower()

    @staticmethod
    def _record_url(record: Dict[str, Any]) -> str:
        return str(record.get("url") or record.get("source_url") or record.get("sourceUrl") or "").strip()

    @classmethod
    def _matches(cls, task: TransferTask, record: Dict[str, Any]) -> bool:
        remote = str(task.remote_task_id or "").strip().lower()
        record_hash = cls._record_hash(record)
        if remote and record_hash and remote == record_hash:
            return True
        if task.source_type == SourceType.MAGNET.value and record_hash:
            return record_hash == str(task.source_key or "").lower()
        record_url = cls._record_url(record)
        return bool(record_url and record_url == task.uri)

    @staticmethod
    def _status_code(record: Dict[str, Any]) -> Optional[int]:
        value = record.get("status")
        if value is None:
            value = record.get("stat")
        if value is None:
            value = record.get("status_code")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _find(self, task: TransferTask) -> Optional[Dict[str, Any]]:
        lookup_hash = str(task.remote_task_id or "").strip()
        if task.source_type == SourceType.MAGNET.value and not lookup_hash:
            lookup_hash = str(task.source_key or "").strip()
        if lookup_hash:
            try:
                detail = self.provider.get_offline_task(lookup_hash)
                for record in self._records(detail):
                    if self._matches(task, record):
                        return record
            except Exception:
                pass

        for page in range(1, 6):
            try:
                response = self.provider.list_offline_tasks(page=page, page_size=30)
            except Exception:
                return None
            records = self._records(response)
            for record in records:
                if self._matches(task, record):
                    return record
            if len(records) < 30:
                break
        return None

    def reconcile_task(self, task: TransferTask) -> TransferTask:
        if task.state != TaskState.TRANSFERRING:
            return task
        if task.source_type not in {SourceType.MAGNET.value, SourceType.ED2K.value}:
            return task
        task.last_checked_at = time()
        record = self._find(task)
        if not record:
            task.extra["remote_missing_last_check"] = task.last_checked_at
            return self.store.save(task)

        task.extra["remote_task"] = record
        record_hash = self._record_hash(record)
        if record_hash and not task.remote_task_id:
            task.remote_task_id = record_hash
        status = self._status_code(record)
        task.extra["remote_status"] = status
        if status in self.COMPLETE_CODES:
            task.error_message = ""
            return self.store.transition(task, TaskState.TRANSFERRED)
        if status in self.FAILED_CODES:
            message = str(
                record.get("error_msg")
                or record.get("error")
                or record.get("message")
                or record.get("name")
                or "115离线任务失败"
            )
            return self.dispatcher.fail(task, TaskState.FAILED_RETRYABLE, message)
        return self.store.save(task)

    def tick(self) -> Dict[str, int]:
        stats = {"checked": 0, "transferred": 0, "failed": 0}
        for task in self.store.list({TaskState.TRANSFERRING}):
            stats["checked"] += 1
            previous = task.state
            current = self.reconcile_task(task)
            if current.state == TaskState.TRANSFERRED and previous != TaskState.TRANSFERRED:
                stats["transferred"] += 1
            elif current.state == TaskState.FAILED_RETRYABLE:
                stats["failed"] += 1
        return stats
