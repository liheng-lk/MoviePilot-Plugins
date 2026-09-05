"""115 网盘助手轻量模型与响应辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Dict


@dataclass(slots=True)
class P115Item:
    file_id: int
    parent_id: int
    name: str
    is_dir: bool
    size: int = 0
    pickcode: str = ""
    sha1: str = ""
    modify_time: int = 0

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "P115Item":
        file_id = raw.get("fid") or raw.get("file_id") or raw.get("cid") or raw.get("id") or 0
        parent_id = raw.get("pid") or raw.get("parent_id") or 0
        name = raw.get("n") or raw.get("file_name") or raw.get("name") or ""
        is_dir = bool(raw.get("cid") and not raw.get("fid")) or str(raw.get("fc") or "") == "0" or bool(raw.get("is_dir"))
        if raw.get("fid"):
            is_dir = False
        size = raw.get("s") or raw.get("size") or 0
        pickcode = raw.get("pc") or raw.get("pick_code") or raw.get("pickcode") or ""
        sha1 = raw.get("sha") or raw.get("sha1") or ""
        modify_time = raw.get("te") or raw.get("t") or raw.get("upt") or raw.get("modify_time") or 0
        return cls(
            file_id=int(file_id or 0),
            parent_id=int(parent_id or 0),
            name=str(name or ""),
            is_dir=bool(is_dir),
            size=int(size or 0),
            pickcode=str(pickcode or ""),
            sha1=str(sha1 or ""),
            modify_time=int(modify_time or 0),
        )

    @property
    def type(self) -> str:
        return "dir" if self.is_dir else "file"

    def as_path(self, parent: str = "/") -> str:
        return str(PurePosixPath(parent) / self.name)

    def modified_datetime(self):
        return datetime.fromtimestamp(self.modify_time) if self.modify_time else None
