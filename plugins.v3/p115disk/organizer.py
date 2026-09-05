"""115 网盘自动整理最小可靠闭环。

监控指定 115 源目录的直属资源：目录整体交给 MoviePilot，根目录散放视频按单文件交给
MoviePilot。插件不自行决定媒体身份、分类、目标目录或命名。失败使用指数退避；MoviePilot
返回成功但源媒体仍可见时进入长冷却，避免重复整理循环。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.schemas.workflow import FileItem
from app.sdk.logging import logger


VIDEO_EXTS = {
    "mkv", "mp4", "ts", "m2ts", "avi", "mov", "wmv", "webm", "mpg", "mpeg", "rmvb", "strm"
}


class P115OrganizerMixin:
    ORGANIZER_DATA_KEY = "p115_organizer_state_v1"

    _organize_enabled: bool = False
    _organize_source_path: str = "/115转存"
    _organize_interval_minutes: int = 1

    @staticmethod
    def _org_norm(path: Any) -> str:
        value = str(path or "/").replace("\\", "/")
        if not value.startswith("/"):
            value = "/" + value
        value = "/" + "/".join(part for part in value.split("/") if part)
        return value.rstrip("/") or "/"

    def _organizer_state(self) -> Dict[str, Dict[str, Any]]:
        raw = self.get_data(self.ORGANIZER_DATA_KEY) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _save_organizer_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        if len(state) > 500:
            ordered = sorted(
                state.items(),
                key=lambda pair: float((pair[1] or {}).get("updated_at") or 0),
                reverse=True,
            )[:500]
            state = dict(ordered)
        self.save_data(self.ORGANIZER_DATA_KEY, state)

    @staticmethod
    def _is_video(item: Any) -> bool:
        return str(getattr(item, "type", "") or "") == "file" and str(
            getattr(item, "extension", "") or ""
        ).lower() in VIDEO_EXTS

    def _collect_media(self, item: Any, max_depth: int = 5) -> List[Any]:
        api = getattr(self, "_storage_api", None)
        if not api or item is None:
            return []
        if self._is_video(item):
            return [item]
        if str(getattr(item, "type", "") or "") != "dir":
            return []
        result: List[Any] = []

        def walk(folder: Any, depth: int) -> None:
            if depth > max_depth:
                return
            for child in api.list(folder) or []:
                if self._is_video(child):
                    result.append(child)
                elif str(getattr(child, "type", "") or "") == "dir":
                    walk(child, depth + 1)

        walk(item, 0)
        return result

    @staticmethod
    def _fingerprint(media: Iterable[Any]) -> str:
        rows = []
        for item in media:
            rows.append(
                "|".join(
                    (
                        str(getattr(item, "fileid", "") or ""),
                        str(getattr(item, "path", "") or ""),
                        str(int(getattr(item, "size", 0) or 0)),
                        str(getattr(item, "modify_time", 0) or 0),
                    )
                )
            )
        rows.sort()
        return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_transfer_result(result: Any) -> Tuple[bool, str]:
        if isinstance(result, tuple):
            success = bool(result[0])
            message = result[1] if len(result) > 1 else ""
        else:
            success = bool(result)
            message = ""
        if isinstance(message, dict):
            message = message.get("message") or str(message)
        return success, str(message or "")

    def _to_workflow_item(self, item: Any) -> FileItem:
        return FileItem(
            storage=self._disk_name,
            fileid=getattr(item, "fileid", None),
            parent_fileid=getattr(item, "parent_fileid", None),
            path=self._org_norm(getattr(item, "path", "/")),
            type=str(getattr(item, "type", "") or "file"),
            name=str(getattr(item, "name", "") or Path(str(getattr(item, "path", ""))).name),
            basename=str(getattr(item, "basename", "") or ""),
            extension=str(getattr(item, "extension", "") or ""),
            size=getattr(item, "size", None),
            modify_time=getattr(item, "modify_time", None),
            pickcode=getattr(item, "pickcode", None),
        )

    def _execute_moviepilot(self, item: Any) -> Tuple[bool, str]:
        from app.chain.transfer import TransferChain

        workflow_item = self._to_workflow_item(item)
        logger.info(
            "【115网盘助手】【自动整理】提交 MoviePilot: %s type=%s",
            workflow_item.path,
            workflow_item.type,
        )
        return self._normalize_transfer_result(
            TransferChain().do_transfer(
                fileitem=workflow_item,
                background=False,
                manual=False,
            )
        )

    @staticmethod
    def _next_retry(attempts: int) -> int:
        schedule = (300, 900, 1800, 3600, 7200, 21600)
        return schedule[min(max(int(attempts), 1) - 1, len(schedule) - 1)]

    def _should_wait(self, row: Dict[str, Any], fingerprint: str, now: float) -> bool:
        if not row or str(row.get("fingerprint") or "") != fingerprint:
            return False
        return float(row.get("next_retry_at") or 0) > now

    def _process_candidate(self, item: Any, state: Dict[str, Dict[str, Any]]) -> None:
        media = self._collect_media(item)
        if not media:
            return
        fingerprint = self._fingerprint(media)
        key = str(getattr(item, "fileid", "") or self._org_norm(getattr(item, "path", "")))
        now = time.time()
        row = dict(state.get(key) or {})
        if self._should_wait(row, fingerprint, now):
            return

        row.update(
            {
                "path": self._org_norm(getattr(item, "path", "")),
                "fingerprint": fingerprint,
                "status": "inflight",
                "updated_at": now,
                "last_error": "",
            }
        )
        state[key] = row
        self._save_organizer_state(state)

        try:
            success, message = self._execute_moviepilot(item)
        except Exception as err:
            success, message = False, str(err)

        try:
            current = getattr(self, "_storage_api", None).get_item(Path(row["path"])) if getattr(self, "_storage_api", None) else None
            remaining = self._collect_media(current) if current else []
            remaining_fp = self._fingerprint(remaining) if remaining else ""
        except Exception as err:
            remaining = media
            remaining_fp = fingerprint
            if not message:
                message = f"源文件复核失败: {err}"

        if success and not remaining:
            row.update(
                {
                    "status": "completed",
                    "attempts": 0,
                    "next_retry_at": 0,
                    "updated_at": time.time(),
                    "last_error": "",
                }
            )
            logger.info("【115网盘助手】【自动整理】终态确认成功: %s", row["path"])
        elif success and remaining_fp == fingerprint:
            row.update(
                {
                    "status": "success_but_source_unchanged",
                    "attempts": int(row.get("attempts") or 0),
                    "next_retry_at": time.time() + 21600,
                    "updated_at": time.time(),
                    "last_error": message or "MoviePilot返回成功但115源媒体仍完整存在",
                }
            )
            logger.warning("【115网盘助手】【自动整理】成功但源未变化，进入6小时冷却: %s", row["path"])
        else:
            attempts = int(row.get("attempts") or 0) + 1
            wait = self._next_retry(attempts)
            row.update(
                {
                    "status": "retry_wait",
                    "attempts": attempts,
                    "next_retry_at": time.time() + wait,
                    "updated_at": time.time(),
                    "last_error": message or "MoviePilot整理未确认成功",
                }
            )
            logger.warning(
                "【115网盘助手】【自动整理】失败，%ss后重试: %s - %s",
                wait,
                row["path"],
                row["last_error"],
            )
        state[key] = row
        self._save_organizer_state(state)

    def organize_monitor_tick(self) -> None:
        if not getattr(self, "_enabled", False) or not self._organize_enabled:
            return
        api = getattr(self, "_storage_api", None)
        if not api:
            return
        source_path = self._org_norm(self._organize_source_path)
        try:
            root = api.get_item(Path(source_path))
            if not root:
                logger.debug("【115网盘助手】【自动整理】监控目录尚不存在: %s", source_path)
                return
            children = list(api.list(root) or [])
        except Exception as err:
            logger.warning("【115网盘助手】【自动整理】读取监控目录失败: %s", err)
            return

        state = self._organizer_state()
        visible_keys = set()
        for item in children:
            if str(getattr(item, "type", "") or "") == "dir" or self._is_video(item):
                key = str(getattr(item, "fileid", "") or self._org_norm(getattr(item, "path", "")))
                visible_keys.add(key)
                self._process_candidate(item, state)

        for key in list(state):
            row = state.get(key) or {}
            row_path = self._org_norm(row.get("path") or "/")
            if self._org_norm(str(Path(row_path).parent)) == source_path and key not in visible_keys:
                state.pop(key, None)
        self._save_organizer_state(state)
