"""115 转存助手内部数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from time import time
from typing import Any, Dict, List, Optional


class SourceType(StrEnum):
    SHARE115 = "share115"
    MAGNET = "magnet"
    ED2K = "ed2k"


class TaskState(StrEnum):
    DISCOVERED = "DISCOVERED"
    RESOLVED = "RESOLVED"
    RESERVED = "RESERVED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TRANSFERRING = "TRANSFERRING"
    TRANSFERRED = "TRANSFERRED"
    ORGANIZE_PENDING = "ORGANIZE_PENDING"
    ORGANIZED = "ORGANIZED"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass(slots=True)
class TransferTask:
    task_id: str
    source_type: str
    source_key: str
    uri: str
    state: str = TaskState.DISCOVERED
    subscribe_id: Optional[int] = None
    tmdb_id: Optional[int] = None
    media_type: str = ""
    season: Optional[int] = None
    target_episodes: List[int] = field(default_factory=list)
    reserved_episodes: List[int] = field(default_factory=list)
    completed_episodes: List[int] = field(default_factory=list)
    target_cid: int = 0
    remote_task_id: str = ""
    wanted: List[int] = field(default_factory=list)
    share_code: str = ""
    receive_code: str = ""
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    last_checked_at: float = 0
    error_code: str = ""
    error_message: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransferTask":
        payload = dict(data or {})
        return cls(**{key: value for key, value in payload.items() if key in cls.__dataclass_fields__})
