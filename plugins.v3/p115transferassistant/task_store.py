"""任务持久化仓库。

依赖 MoviePilot 插件基类提供的 get_data/save_data；这里不绑定具体宿主，便于单测。
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from .models import TaskState, TransferTask


class TaskStore:
    DATA_KEY = "p115_transfer_tasks_v1"

    def __init__(self, load: Callable[[str], object], save: Callable[[str, object], object]):
        self._load = load
        self._save = save

    def _read_all(self) -> Dict[str, dict]:
        raw = self._load(self.DATA_KEY) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _write_all(self, data: Dict[str, dict]) -> None:
        self._save(self.DATA_KEY, data)

    def get(self, task_id: str) -> Optional[TransferTask]:
        data = self._read_all().get(task_id)
        return TransferTask.from_dict(data) if isinstance(data, dict) else None

    def list(self, states: Optional[Iterable[str]] = None) -> List[TransferTask]:
        state_set = {str(state) for state in states or []}
        result: List[TransferTask] = []
        for payload in self._read_all().values():
            if not isinstance(payload, dict):
                continue
            task = TransferTask.from_dict(payload)
            if state_set and str(task.state) not in state_set:
                continue
            result.append(task)
        result.sort(key=lambda item: item.updated_at, reverse=True)
        return result

    def save(self, task: TransferTask) -> TransferTask:
        task.touch()
        data = self._read_all()
        data[task.task_id] = task.to_dict()
        self._write_all(data)
        return task

    def transition(self, task: TransferTask, state: TaskState | str, *, error: str = "") -> TransferTask:
        task.state = str(getattr(state, "value", state))
        if error:
            task.error_message = error[:1000]
        return self.save(task)

    def active_source_keys(self) -> set[str]:
        active = {
            TaskState.DISCOVERED,
            TaskState.RESOLVED,
            TaskState.RESERVED,
            TaskState.TRANSFER_PENDING,
            TaskState.TRANSFERRING,
            TaskState.TRANSFERRED,
            TaskState.ORGANIZE_PENDING,
            TaskState.ORGANIZED,
        }
        return {task.source_key for task in self.list(active)}

    def terminal_source_keys(self) -> set[str]:
        return {
            task.source_key
            for task in self.list({TaskState.COMPLETED, TaskState.FAILED_FINAL})
        }
