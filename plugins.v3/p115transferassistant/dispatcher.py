"""三来源提交与集级安全门禁。"""

from __future__ import annotations

from typing import Iterable, Optional

from .episode_fence import EpisodeFence
from .models import SourceType, TaskState, TransferTask
from .p115_provider import P115TransferProvider
from .resource import NormalizedResource
from .task_store import TaskStore


class TransferDispatcher:
    def __init__(
        self,
        provider: P115TransferProvider,
        store: TaskStore,
        fence: EpisodeFence | None = None,
    ):
        self.provider = provider
        self.store = store
        self.fence = fence

    def build_task(
        self,
        resource: NormalizedResource,
        *,
        target_cid: int,
        subscribe_id: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        media_type: str = "",
        season: Optional[int] = None,
        target_episodes: Optional[Iterable[int]] = None,
        wanted: Optional[Iterable[int]] = None,
    ) -> TransferTask:
        existing = self.store.get(resource.task_id)
        if existing:
            return existing
        task = TransferTask(
            task_id=resource.task_id,
            source_type=str(resource.source_type.value),
            source_key=resource.source_key,
            uri=resource.uri,
            subscribe_id=subscribe_id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            season=season,
            target_episodes=sorted({int(v) for v in (target_episodes or []) if int(v) > 0}),
            target_cid=int(target_cid or 0),
            wanted=sorted({int(v) for v in (wanted or []) if int(v) >= 0}),
            share_code=resource.share_code,
            receive_code=resource.receive_code,
        )
        return self.store.save(task)

    def _release_reservation(self, task: TransferTask) -> None:
        if not self.fence or not task.reserved_episodes:
            return
        self.fence.release(
            task_id=task.task_id,
            tmdb_id=task.tmdb_id,
            season=task.season,
            episodes=task.reserved_episodes,
        )
        task.reserved_episodes = []
        self.store.save(task)

    def fail(
        self,
        task: TransferTask,
        state: TaskState,
        error: str,
        *,
        release: bool = True,
    ) -> TransferTask:
        task = self.store.transition(task, state, error=error)
        if release:
            self._release_reservation(task)
        return task

    def dispatch(self, task: TransferTask, *, share_file_ids: Optional[Iterable[int]] = None) -> TransferTask:
        if task.state in {TaskState.COMPLETED, TaskState.TRANSFERRING, TaskState.TRANSFERRED}:
            return task
        self.store.transition(task, TaskState.TRANSFER_PENDING)
        try:
            if task.source_type == SourceType.SHARE115.value:
                file_ids = [int(v) for v in (share_file_ids or [])]
                if not file_ids:
                    return self.fail(task, TaskState.NEEDS_REVIEW, "115 分享尚未解析出安全文件选择")
                resp = self.provider.share_receive(
                    share_code=task.share_code,
                    receive_code=task.receive_code,
                    file_ids=file_ids,
                    target_cid=task.target_cid,
                )
            elif task.source_type == SourceType.MAGNET.value:
                if not task.wanted:
                    return self.fail(task, TaskState.NEEDS_REVIEW, "Magnet 尚未生成安全 wanted 文件索引")
                resp = self.provider.offline_add_bt(
                    info_hash=task.source_key,
                    target_cid=task.target_cid,
                    wanted=task.wanted,
                )
            elif task.source_type == SourceType.ED2K.value:
                resp = self.provider.offline_add_url(uri=task.uri, target_cid=task.target_cid)
            else:
                return self.fail(task, TaskState.FAILED_FINAL, f"未知来源: {task.source_type}")

            if not self.provider.is_ok(resp):
                message = (
                    str(resp.get("error") or resp.get("message") or resp)[:1000]
                    if isinstance(resp, dict)
                    else str(resp)
                )
                return self.fail(task, TaskState.FAILED_RETRYABLE, message)

            task.extra["submit_response"] = resp
            remote_id = ""
            if isinstance(resp, dict):
                data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
                remote_id = str(
                    data.get("task_id")
                    or data.get("taskId")
                    or data.get("info_hash")
                    or data.get("hash")
                    or ""
                )
            task.remote_task_id = remote_id
            task.error_code = ""
            task.error_message = ""
            if task.source_type == SourceType.SHARE115.value:
                # share_receive 返回成功时文件已保存到目标 CID；后续只等 P115Disk/MP 整理。
                return self.store.transition(task, TaskState.TRANSFERRED)
            return self.store.transition(task, TaskState.TRANSFERRING)
        except ValueError as err:
            return self.fail(task, TaskState.NEEDS_REVIEW, str(err))
        except Exception as err:
            return self.fail(task, TaskState.FAILED_RETRYABLE, str(err))
