"""光鸭转存助手 v1.8.0 多来源与原生云添加层。

核心原则：
- Magnet 与 ED2K 都是“订阅来源”，不是 MoviePilot 下载器任务；
- 两种链接统一调用光鸭云盘原生 cloudcollection 云添加接口；
- resolve_res -> create_task -> list_task 构成可恢复状态机；
- 外部来源一旦绑定订阅，继续沿用已有固定分流门禁，避免原生下载重复获取；
- “观影”按 MoviePilot 订阅模式接入：已有订阅可直接绑定 Magnet/ED2K 来源。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .legacy import _episode_numbers, _is_subtitle, _is_video, _normalize_media_text
from .source_store_v180 import GuangYaSourceStoreMixin
from .source_types_v180 import (
    SOURCE_INFLIGHT_STATES,
    SOURCE_PENDING_STATES,
    normalize_source_uri,
)


class GuangYaMultiSourceMixin(GuangYaSourceStoreMixin):
    """Magnet/ED2K -> 光鸭原生云添加，并提供 MoviePilot 观影订阅接入口。"""

    build_id = "20260901-r1"
    _offline_batch_limit = 20
    # 服务端任务已经 completed、但 list_task 未返回可验证视频文件名时，
    # 最多保留一段“远端完成待核验”窗口。窗口结束后必须解除 episode claim，
    # 否则一个信息不完整的回执会永久阻塞后续候选。
    _offline_remote_verify_grace_seconds = 20 * 60

    def init_plugin(self, config: dict = None) -> None:
        self._offline_lock = threading.RLock()
        self._offline_worker_lock = threading.Lock()
        self._offline_worker_ids: set[str] = set()
        super().init_plugin(config)

    def _claim_source_dispatch_slot(self, source_id: str) -> bool:
        source_id = str(source_id or "").strip()
        if not source_id:
            return False
        lock = getattr(self, "_offline_worker_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._offline_worker_lock = lock
        with lock:
            workers = getattr(self, "_offline_worker_ids", None)
            if not isinstance(workers, set):
                workers = set()
                self._offline_worker_ids = workers
            if source_id in workers:
                return False
            workers.add(source_id)
            return True

    def _release_source_dispatch_slot(self, source_id: str) -> None:
        source_id = str(source_id or "").strip()
        if not source_id:
            return
        lock = getattr(self, "_offline_worker_lock", None)
        workers = getattr(self, "_offline_worker_ids", None)
        if lock is None or not isinstance(workers, set):
            return
        with lock:
            workers.discard(source_id)

    # ------------------------------------------------------------------
    # 光鸭原生云添加 API
    # ------------------------------------------------------------------
    @staticmethod
    def _offline_api_success(response: Any) -> bool:
        if not isinstance(response, dict):
            return False
        if response.get("error"):
            return False
        msg = str(response.get("msg") or "").strip().lower()
        code = response.get("code")
        if msg == "success":
            return True
        if msg:
            return False
        return code in (None, 0, "0")

    @staticmethod
    def _offline_api_error(response: Any, fallback: str) -> str:
        if not isinstance(response, dict):
            return fallback
        return str(
            response.get("error_description")
            or response.get("error")
            or response.get("msg")
            or response.get("message")
            or fallback
        )[:500]

    def _offline_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用光鸭原生 cloudcollection；优先使用客户端公开方法，兼容旧客户端。"""
        client, _ = self._get_guangya_runtime()
        if not client:
            raise RuntimeError("光鸭云盘助手未运行或未登录")

        endpoint = str(endpoint or "").strip()
        method_map = {
            "/cloudcollection/v1/resolve_res": "cloudcollection_resolve_res",
            "/cloudcollection/v1/create_task": "cloudcollection_task_create",
            "/cloudcollection/v1/list_task": "cloudcollection_task_list",
            "/cloudcollection/v2/retry_task": "cloudcollection_task_retry",
            "/cloudcollection/v2/delete_task": "cloudcollection_task_delete",
        }
        method_name = method_map.get(endpoint)
        method = getattr(client, method_name, None) if method_name else None
        if callable(method):
            result = method(payload)
            return result if isinstance(result, dict) else {"msg": "error", "error": str(result)}

        request = getattr(client, "_request", None)
        base_url = str(getattr(client, "API_BASE_URL", "https://api.guangyapan.com") or "").rstrip("/")
        if not callable(request):
            raise RuntimeError("当前光鸭客户端缺少 cloudcollection 请求能力")
        result = request(
            method="POST",
            url=f"{base_url}{endpoint}",
            data=dict(payload or {}),
        )
        return result if isinstance(result, dict) else {"msg": "error", "error": str(result)}

    def _offline_target_parent(self, subscribe: Any) -> Tuple[str, str]:
        """复用光鸭存储插件创建/解析目标目录，返回 path 与 parentId。"""
        _, api = self._get_guangya_runtime()
        if not api:
            raise RuntimeError("光鸭云盘助手存储运行时不可用")
        target_path = str(self._target_path(subscribe) or "/")
        folder = api.get_folder(Path(target_path))
        if not folder:
            raise RuntimeError(f"无法创建或定位光鸭目标目录：{target_path}")
        parent_id = "" if target_path.rstrip("/") in ("", "/") else str(folder.fileid or "")
        if target_path.rstrip("/") not in ("", "/") and not parent_id:
            raise RuntimeError(f"光鸭目标目录缺少 fileId：{target_path}")
        return target_path, parent_id

    @staticmethod
    def _offline_resolved_data(response: Dict[str, Any]) -> Dict[str, Any]:
        data = response.get("data") or {}
        return dict(data) if isinstance(data, dict) else {}

    def _select_offline_file_indexes(self, subscribe: Any, resolve_data: Dict[str, Any]) -> List[int]:
        """磁力解析后仅选择媒体/字幕，并在可识别时优先缺集。"""
        bt_info = resolve_data.get("btResInfo") or {}
        if not isinstance(bt_info, dict):
            return []
        subfiles = bt_info.get("subfiles") or []
        if not isinstance(subfiles, list) or not subfiles:
            return []

        all_indexes: List[int] = []
        media_rows: List[Tuple[int, str, int]] = []
        for fallback_index, raw in enumerate(subfiles):
            if not isinstance(raw, dict):
                continue
            value = raw.get("fileIndex")
            try:
                index = int(value) if value is not None else fallback_index
            except (TypeError, ValueError):
                index = fallback_index
            name = str(raw.get("fileName") or "").strip()
            try:
                size = int(raw.get("fileSize") or 0)
            except (TypeError, ValueError):
                size = 0
            all_indexes.append(index)
            if _is_video(name) or _is_subtitle(name):
                media_rows.append((index, name, size))

        if not bool(getattr(self, "_media_only", True)):
            return all_indexes
        if not media_rows:
            return []

        # 电视剧存在明确缺集时，只下载能确认覆盖缺集的文件；弱命名文件仍保留，交给
        # 光鸭云盘助手/MoviePilot 后续整理识别，不因解析失败直接丢弃真实正片。
        if not self._is_movie_subscription(subscribe):
            missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe) or []) if int(v or 0) > 0)
            if missing:
                selected: List[int] = []
                weak: List[int] = []
                for index, name, _ in media_rows:
                    _, episodes = _episode_numbers(name)
                    if not episodes:
                        weak.append(index)
                        continue
                    if set(int(v) for v in episodes).intersection(missing):
                        selected.append(index)
                if selected:
                    return list(dict.fromkeys([*selected, *weak]))

        return list(dict.fromkeys(index for index, _, _ in media_rows))

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        response = self._offline_request(
            "/cloudcollection/v1/resolve_res",
            {"url": str(source.get("uri") or "")},
        )
        if not self._offline_api_success(response):
            raise RuntimeError(self._offline_api_error(response, "光鸭云添加解析失败"))
        data = self._offline_resolved_data(response)
        bt_info = data.get("btResInfo") or {}
        resolved_name = ""
        if isinstance(bt_info, dict):
            resolved_name = str(bt_info.get("fileName") or "").strip()
        resolved_name = resolved_name or str(source.get("name") or source.get("label") or "").strip()
        resolved_url = str(data.get("url") or source.get("uri") or "").strip()
        indexes = self._select_offline_file_indexes(subscribe, data)
        subfiles = bt_info.get("subfiles") if isinstance(bt_info, dict) else None
        if bool(getattr(self, "_media_only", True)) and isinstance(subfiles, list) and subfiles and not indexes:
            raise RuntimeError("光鸭已解析来源，但未发现可选的视频或字幕文件")
        return {
            "resolved_name": resolved_name[:300],
            "resolved_url": resolved_url,
            "selected_indexes": indexes,
            "resolve_data": data,
        }

    def _mark_offline_failure(
        self,
        source: Dict[str, Any],
        error: Exception | str,
        *,
        attempt_increment: bool = True,
    ) -> Dict[str, Any]:
        attempts = int(source.get("attempts") or 0) + (1 if attempt_increment else 0)
        terminal = attempts >= int(self._offline_max_attempts or 3)
        state = "failed" if terminal else "retry"
        next_retry_at = 0.0 if terminal else time.time() + int(self._offline_retry_minutes or 15) * 60
        updated = self._update_source(
            str(source.get("id") or ""),
            state=state,
            attempts=attempts,
            last_error=str(error)[:500],
            next_retry_at=next_retry_at,
        ) or source
        self._plugin_log(
            "WARNING",
            "【光鸭转存助手】【原生云添加】来源 %s 处理失败，state=%s attempts=%s：%s",
            str(source.get("id") or ""),
            state,
            attempts,
            error,
        )
        return updated

    def _submit_offline_source_base_v180(self, source_id: str) -> Dict[str, Any]:
        store = self._source_store()
        source = dict(store["items"].get(str(source_id)) or {})
        if not source:
            return {"success": False, "message": "来源不存在"}
        if not source.get("enabled", True):
            return {"success": False, "message": "来源已禁用"}
        if str(source.get("type") or "") not in {"magnet", "ed2k"}:
            return {"success": False, "message": "该来源不属于原生云添加类型"}

        subscribe = self._find_subscription(int(source.get("subscribe_id") or 0))
        if not subscribe:
            return self._mark_offline_failure(source, "绑定的 MoviePilot 订阅已不存在")

        task_id = str(source.get("task_id") or "").strip()
        if task_id and str(source.get("state") or "") in {"retry", "failed"}:
            return self._retry_offline_task(source)
        if task_id and str(source.get("state") or "") in SOURCE_INFLIGHT_STATES:
            return self._poll_offline_source(source)
        if str(source.get("state") or "") == "completed":
            return {"success": True, "message": "来源已完成", "data": source}

        self._update_source(str(source_id), state="dispatching", last_error="")
        try:
            target_path, parent_id = self._offline_target_parent(subscribe)
            resolved = self._resolve_offline_source(source, subscribe)
            # Final submit gate: selected indexes must contain at least one video when enumerated.
            gate = getattr(self, "_assert_selected_video_present_v210", None)
            if callable(gate) and resolved.get("selected_indexes"):
                try:
                    manifest = gate(
                        resolve_data=resolved.get("resolve_data") or {},
                        selected_indexes=list(resolved.get("selected_indexes") or []),
                        source=source,
                        subscribe=subscribe,
                    )
                    if manifest:
                        resolved["selected_manifest"] = manifest
                except RuntimeError as err:
                    if "SELECTED_VIDEO_MISSING" in str(err):
                        failed = self._mark_offline_failure(source, err)
                        self._writeback_offline_candidate_diag_v209(
                            failed or source,
                            state="FAILED_RETRYABLE",
                            reason_code="SELECTED_VIDEO_MISSING",
                            stage="SUBMIT_PRECHECK",
                            message=str(err)[:360],
                        )
                        return {"success": False, "message": str(err), "data": failed}
                    raise
            payload: Dict[str, Any] = {
                "url": resolved["resolved_url"] or str(source.get("uri") or ""),
                "parentId": parent_id,
            }
            if resolved["selected_indexes"]:
                payload["fileIndexes"] = resolved["selected_indexes"]
            # newName 只作为显式标签；默认让光鸭保留解析出的资源名，避免与媒体目录重复嵌套。
            if str(source.get("label") or "").strip():
                payload["newName"] = str(source.get("label") or "").strip()[:200]

            manifest = list(resolved.get("selected_manifest") or [])
            video_indexes = [
                int(row.get("file_index"))
                for row in manifest
                if str(row.get("type") or "") == "video" and str(row.get("file_index") or "").lstrip("-").isdigit()
            ]
            subtitle_indexes = [
                int(row.get("file_index"))
                for row in manifest
                if str(row.get("type") or "") == "subtitle" and str(row.get("file_index") or "").lstrip("-").isdigit()
            ]
            self._plugin_log(
                "INFO",
                "【云添加提交摘要】source=%s fileIndexes=%s selected_video_indexes=%s selected_subtitle_indexes=%s",
                str(source.get("type") or "").upper(),
                list(resolved.get("selected_indexes") or [])[:40],
                video_indexes[:40],
                subtitle_indexes[:40],
            )

            response = self._offline_request("/cloudcollection/v1/create_task", payload)
            if not self._offline_api_success(response):
                raise RuntimeError(self._offline_api_error(response, "创建光鸭云添加任务失败"))
            data = self._offline_resolved_data(response)
            task_id = str(data.get("taskId") or "").strip()
            if not task_id:
                raise RuntimeError("光鸭返回成功但未提供云添加 taskId")

            attempts = int(source.get("attempts") or 0) + 1
            updated = self._update_source(
                str(source_id),
                state="submitted",
                attempts=attempts,
                task_id=task_id,
                task_status=0,
                progress=0,
                resolved_name=resolved["resolved_name"],
                resolved_url=resolved["resolved_url"],
                selected_indexes=resolved["selected_indexes"],
                selected_manifest=list(resolved.get("selected_manifest") or [])[:80],
                target_path=target_path,
                last_error="",
                next_retry_at=0,
                submitted_at=self._now_text(),
            ) or source
            self._record_route_health(
                last_offline_submit_at=self._now_text(),
                last_offline_submit_id=str(source_id),
                last_offline_task_id=task_id,
                last_offline_source_type=str(source.get("type") or ""),
            )
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【原生云添加】%s 已提交到光鸭 task=%s target=%s files=%s",
                str(source.get("type") or "").upper(),
                task_id,
                target_path,
                len(resolved["selected_indexes"]),
            )
            self._writeback_offline_candidate_diag_v209(
                updated or source,
                state="PENDING",
                reason_code="REMOTE_TASK_PENDING",
                stage="SUBMIT",
                message="已提交光鸭原生云添加",
            )
            return {"success": True, "message": "已提交光鸭原生云添加", "data": updated}
        except Exception as err:
            latest = dict(self._source_store()["items"].get(str(source_id)) or source)
            failed = self._mark_offline_failure(latest, err)
            self._writeback_offline_candidate_diag_v209(
                failed or latest,
                state="FAILED_RETRYABLE",
                reason_code="CLOUD_TASK_SUBMIT_FAILED",
                stage="SUBMIT",
                message=str(err)[:360],
            )
            return {"success": False, "message": str(err), "data": failed}

    def _retry_offline_task(self, source: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(source.get("task_id") or "").strip()
        if not task_id:
            # 还没有服务端任务，重新执行 resolve/create。
            self._update_source(str(source.get("id") or ""), state="new", next_retry_at=0)
            return self._submit_offline_source(str(source.get("id") or ""))
        try:
            response = self._offline_request(
                "/cloudcollection/v2/retry_task",
                {"taskIds": [task_id]},
            )
            if not self._offline_api_success(response):
                raise RuntimeError(self._offline_api_error(response, "光鸭云添加重试失败"))
            attempts = int(source.get("attempts") or 0) + 1
            updated = self._update_source(
                str(source.get("id") or ""),
                state="waiting",
                attempts=attempts,
                last_error="",
                next_retry_at=0,
                retried_at=self._now_text(),
            ) or source
            return {"success": True, "message": "已请求光鸭重试云添加任务", "data": updated}
        except Exception as err:
            return {"success": False, "message": str(err), "data": self._mark_offline_failure(source, err)}

    @staticmethod
    def _offline_task_rows(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = response.get("data") or {}
        if not isinstance(data, dict):
            return []
        rows = data.get("list") or data.get("items") or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _poll_offline_source_base_v180(self, source: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(source.get("task_id") or "").strip()
        if not task_id:
            return {"success": False, "message": "来源还没有云添加 taskId", "data": source}
        try:
            response = self._offline_request(
                "/cloudcollection/v1/list_task",
                {"taskIds": [task_id], "pageSize": 10},
            )
            if not self._offline_api_success(response):
                raise RuntimeError(self._offline_api_error(response, "读取光鸭云添加任务失败"))
            rows = self._offline_task_rows(response)
            task = next((row for row in rows if str(row.get("taskId") or "") == task_id), None)
            if not task:
                updated = self._update_source(
                    str(source.get("id") or ""),
                    state="waiting",
                    last_error="任务暂未出现在光鸭任务列表，保留 taskId 等待下次轮询",
                ) or source
                return {"success": True, "message": "任务等待光鸭列表回执", "data": updated}

            try:
                status = int(task.get("status"))
            except (TypeError, ValueError):
                status = -1
            try:
                progress = max(0, min(100, int(task.get("progress") or 0)))
            except (TypeError, ValueError):
                progress = 0
            file_id = str(task.get("fileId") or "").strip()
            file_name = str(task.get("fileName") or source.get("resolved_name") or "").strip()

            if status == 2:
                # Task completed: do not treat "plan had video" or "empty manifest" as remote video confirmed.
                manifest = list(source.get("selected_manifest") or [])
                planned_video = [
                    str(row.get("name") or "")
                    for row in manifest
                    if str(row.get("type") or "") == "video" or _is_video(str(row.get("name") or ""))
                ]
                planned_subtitle = [
                    str(row.get("name") or "")
                    for row in manifest
                    if str(row.get("type") or "") == "subtitle" or _is_subtitle(str(row.get("name") or ""))
                ]
                file_name = str(task.get("fileName") or source.get("resolved_name") or "").strip()
                base_name = file_name.rsplit("/", 1)[-1] if file_name else ""

                if manifest and not planned_video:
                    updated = self._update_source(
                        str(source.get("id") or ""),
                        state="failed",
                        task_status=status,
                        progress=100,
                        file_id=file_id,
                        resolved_name=file_name[:300],
                        last_error="REMOTE_VIDEO_MISSING: 任务完成但选中清单无正片视频",
                        next_retry_at=0,
                        remote_video_confirmed=False,
                        remote_verify_source="selected_manifest",
                    ) or source
                    self._writeback_offline_candidate_diag_v209(
                        updated,
                        state="FAILED_RETRYABLE",
                        reason_code="REMOTE_VIDEO_MISSING",
                        stage="REMOTE_VERIFY",
                        message="云添加任务完成但未确认正片视频",
                    )
                    self._plugin_log(
                        "WARNING",
                        "【云添加终态】task_id=%s status=completed manifest_present=True "
                        "planned_video=0 planned_subtitle=%s remote_result_name=%s "
                        "remote_video_verified=False verify_source=selected_manifest",
                        task_id,
                        len(planned_subtitle),
                        base_name[:180] or "-",
                    )
                    return {"success": False, "message": updated.get("last_error"), "data": updated}

                if file_name and _is_subtitle(file_name) and not planned_video and not _is_video(file_name):
                    updated = self._update_source(
                        str(source.get("id") or ""),
                        state="failed",
                        task_status=status,
                        progress=100,
                        file_id=file_id,
                        resolved_name=file_name[:300],
                        last_error="REMOTE_VIDEO_MISSING: 任务完成文件名为字幕",
                        next_retry_at=0,
                        remote_video_confirmed=False,
                        remote_verify_source="task_result_filename",
                    ) or source
                    self._writeback_offline_candidate_diag_v209(
                        updated,
                        state="FAILED_RETRYABLE",
                        reason_code="REMOTE_VIDEO_MISSING",
                        stage="REMOTE_VERIFY",
                        message="云添加任务完成但文件名仅为字幕",
                    )
                    self._plugin_log(
                        "WARNING",
                        "【云添加终态】task_id=%s status=completed manifest_present=%s "
                        "planned_video=%s planned_subtitle=%s remote_result_name=%s "
                        "remote_video_verified=False verify_source=task_result_filename",
                        task_id,
                        bool(manifest),
                        len(planned_video),
                        len(planned_subtitle),
                        base_name[:180] or "-",
                    )
                    return {"success": False, "message": updated.get("last_error"), "data": updated}

                # Confirmation policy:
                # - task_result filename is a real video extension → confirmed via task_result_filename
                # - otherwise planned_manifest only proves selection intent, not remote landing
                # - empty/missing manifest without video filename → UNKNOWN (no auto-confirm)
                if file_name and _is_video(file_name):
                    verified = True
                    verify_source = "task_result_filename"
                elif planned_video:
                    verified = False
                    verify_source = "planned_manifest"
                else:
                    verified = False
                    verify_source = "legacy_compat" if not manifest else "selected_manifest"

                now_ts = time.time()
                try:
                    pending_verify_since = float(source.get("pending_verify_since") or 0)
                except (TypeError, ValueError):
                    pending_verify_since = 0.0
                if not verified and pending_verify_since <= 0:
                    pending_verify_since = now_ts

                subscribe = self._find_subscription(int(source.get("subscribe_id") or 0))

                # “媒体库观察”只能用来结束重复占位，绝不能伪造成这个来源的成功回执。
                # 如果远端 task 已完成但回执缺少视频文件名，而 Emby 已经看到本 source
                # 的全部目标集，则停止该 source 的 claim，并明确标成 unattributed。
                if not verified and subscribe and not self._is_movie_subscription(subscribe):
                    target_eps = set()
                    for raw in source.get("resolved_episodes") or source.get("target_episodes") or []:
                        try:
                            value = int(raw)
                        except (TypeError, ValueError):
                            continue
                        if value > 0:
                            target_eps.add(value)
                    if target_eps:
                        try:
                            sync = dict(self._sync_media_library_progress(subscribe) or {})
                        except Exception as err:
                            sync = {}
                            self._plugin_log(
                                "DEBUG",
                                "【光鸭转存助手】【远端完成待核验】媒体库核验暂不可用：source=%s error=%s",
                                str(source.get("id") or "")[:60],
                                str(err)[:260],
                            )
                        existing = set()
                        if bool(sync.get("success")):
                            for raw in sync.get("existing") or []:
                                try:
                                    value = int(raw)
                                except (TypeError, ValueError):
                                    continue
                                if value > 0:
                                    existing.add(value)
                        if target_eps and target_eps.issubset(existing):
                            updated = self._update_source(
                                str(source.get("id") or ""),
                                state="disabled",
                                enabled=False,
                                auto_dispatch=False,
                                task_status=status,
                                progress=100,
                                file_id=file_id,
                                resolved_name=file_name[:300],
                                last_error=(
                                    "REMOTE_RECEIPT_UNVERIFIED: 服务端任务已完成，媒体库已满足目标；"
                                    "已停止占位，但不把媒体库观察归因成该来源成功"
                                ),
                                next_retry_at=0,
                                remote_video_confirmed=False,
                                remote_verify_source="library_satisfied_unattributed",
                                pending_verify_since=pending_verify_since,
                                library_observed_episodes=sorted(target_eps),
                            ) or source
                            self._writeback_offline_candidate_diag_v209(
                                updated,
                                state="SKIPPED",
                                reason_code="LIBRARY_ALREADY_SATISFIED",
                                stage="REMOTE_VERIFY",
                                message="媒体库已满足目标；远端来源回执不足，停止占位但不记来源成功",
                            )
                            self._plugin_log(
                                "INFO",
                                "【云添加终态】task_id=%s status=completed source=%s "
                                "remote_video_verified=False verify_source=library_satisfied_unattributed "
                                "episodes=%s action=release_claim_without_receipt",
                                task_id,
                                str(source.get("id") or "")[:60],
                                ",".join(str(v) for v in sorted(target_eps)) or "-",
                            )
                            return {
                                "success": True,
                                "handled": True,
                                "skipped": True,
                                "verified": False,
                                "reason": "library_satisfied_unattributed",
                                "message": "媒体库已满足目标，已停止该来源占位；未把媒体库观察记为来源成功",
                                "data": updated,
                            }

                # 远端 completed 但无法验证正片时不能永久 waiting。
                # 超过 grace window 后转为 needs_review，释放 episode claim，让下一候选可继续。
                if not verified:
                    grace = max(
                        300,
                        int(getattr(
                            self,
                            "_offline_remote_verify_grace_seconds",
                            20 * 60,
                        ) or 20 * 60),
                    )
                    if (now_ts - pending_verify_since) >= grace:
                        updated = self._update_source(
                            str(source.get("id") or ""),
                            state="needs_review",
                            task_status=status,
                            progress=100,
                            file_id=file_id,
                            resolved_name=file_name[:300],
                            last_error=(
                                "REMOTE_VERIFY_TIMEOUT: 服务端任务已完成，但在核验窗口内仍无法确认远端正片；"
                                "已释放自动占位，允许后续候选继续"
                            ),
                            next_retry_at=0,
                            remote_video_confirmed=False,
                            remote_verify_source="timeout_unverified",
                            pending_verify_since=pending_verify_since,
                            pending_verify_expired_at=now_ts,
                        ) or source
                        self._writeback_offline_candidate_diag_v209(
                            updated,
                            state="FAILED_RETRYABLE",
                            reason_code="REMOTE_VERIFY_FAILED",
                            stage="REMOTE_VERIFY",
                            message="服务端任务完成但正片回执长期无法确认，已释放占位等待其它候选",
                        )
                        self._plugin_log(
                            "WARNING",
                            "【云添加终态】task_id=%s status=completed source=%s "
                            "remote_video_verified=False verify_source=timeout_unverified "
                            "pending_seconds=%s action=release_claim_for_fallback",
                            task_id,
                            str(source.get("id") or "")[:60],
                            int(now_ts - pending_verify_since),
                        )
                        return {
                            "success": False,
                            "handled": True,
                            "reason": "remote_verify_timeout",
                            "message": str(updated.get("last_error") or "远端正片核验超时"),
                            "data": updated,
                        }

                completed_state = "completed" if verified else "waiting"
                reason_code = "REMOTE_VERIFY_CONFIRMED" if verified else "REMOTE_TASK_PENDING"
                diag_state = "SUCCESS" if verified else "PENDING"
                diag_message = (
                    "光鸭原生云添加已确认正片"
                    if verified
                    else "云添加任务完成，正片远端核验待确认"
                )

                updated = self._update_source(
                    str(source.get("id") or ""),
                    state=completed_state,
                    task_status=status,
                    progress=100,
                    file_id=file_id,
                    resolved_name=file_name[:300],
                    completed_at=self._now_text() if verified else str(source.get("completed_at") or ""),
                    completed_ts=now_ts if verified else float(source.get("completed_ts") or 0),
                    last_error="" if verified else "PENDING_VERIFY: 任务完成但远端正片未确认",
                    next_retry_at=0,
                    remote_video_confirmed=bool(verified),
                    remote_verify_source=verify_source,
                    pending_verify_since=0 if verified else pending_verify_since,
                ) or source
                if verified:
                    self._record_route_health(
                        last_offline_completed_at=self._now_text(),
                        last_offline_completed_id=str(source.get("id") or ""),
                        last_offline_task_id=task_id,
                    )
                else:
                    self._record_route_health(
                        last_offline_pending_verify_at=self._now_text(),
                        last_offline_pending_verify_id=str(source.get("id") or ""),
                        last_offline_pending_verify_task_id=task_id,
                    )
                if subscribe and verified:
                    try:
                        self._sync_media_library_progress(subscribe)
                    except Exception as err:
                        self._plugin_log("DEBUG", "【光鸭转存助手】【原生云添加】完成后媒体库进度同步暂未命中：%s", err)
                self._plugin_log(
                    "INFO",
                    "【云添加终态】task_id=%s status=completed manifest_present=%s "
                    "planned_video=%s planned_subtitle=%s remote_result_name=%s "
                    "remote_video_verified=%s verify_source=%s",
                    task_id,
                    bool(manifest),
                    len(planned_video),
                    len(planned_subtitle),
                    base_name[:180] or "-",
                    bool(verified),
                    verify_source,
                )
                self._writeback_offline_candidate_diag_v209(
                    updated or source,
                    state=diag_state,
                    reason_code=reason_code,
                    stage="REMOTE_VERIFY",
                    message=diag_message,
                )
                return {
                    "success": bool(verified),
                    "message": diag_message,
                    "data": updated,
                }

            if status == 5:
                attempts = int(source.get("attempts") or 0)
                if attempts >= int(self._offline_max_attempts or 3):
                    updated = self._update_source(
                        str(source.get("id") or ""),
                        state="failed",
                        task_status=status,
                        progress=progress,
                        file_id=file_id,
                        last_error="光鸭任务部分完成或添加失败，已达到自动重试上限",
                        next_retry_at=0,
                    ) or source
                    self._writeback_offline_candidate_diag_v209(
                        updated,
                        state="FAILED_FINAL",
                        reason_code="REMOTE_VERIFY_FAILED",
                        stage="REMOTE_VERIFY",
                        message=str(updated.get("last_error") or "光鸭任务失败"),
                    )
                    return {"success": False, "message": updated.get("last_error"), "data": updated}
                updated = self._update_source(
                    str(source.get("id") or ""),
                    state="retry",
                    task_status=status,
                    progress=progress,
                    file_id=file_id,
                    last_error="光鸭任务部分完成或添加失败，等待原生任务重试",
                    next_retry_at=time.time() + int(self._offline_retry_minutes or 15) * 60,
                ) or source
                return {"success": False, "message": updated.get("last_error"), "data": updated}

            state = "queued" if status == 0 else "waiting"
            updated = self._update_source(
                str(source.get("id") or ""),
                state=state,
                task_status=status,
                progress=progress,
                file_id=file_id,
                resolved_name=file_name[:300],
                last_error="",
            ) or source
            return {"success": True, "message": f"光鸭云添加进行中 {progress}%", "data": updated}
        except Exception as err:
            # 轮询网络异常不增加提交 attempts，避免临时网络故障把有效任务打入永久失败。
            updated = self._mark_offline_failure(source, err, attempt_increment=False)
            if str(updated.get("state") or "") == "retry":
                updated = self._update_source(
                    str(source.get("id") or ""),
                    state="waiting",
                    next_retry_at=0,
                    last_error=f"任务轮询暂时失败：{str(err)[:400]}",
                ) or updated
            return {"success": False, "message": str(err), "data": updated}

    # ------------------------------------------------------------------
    # 调度与 API
    # ------------------------------------------------------------------
    def _spawn_source_dispatch(self, source_id: str) -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        if not source_id:
            return {"success": False, "message": "来源 ID 不能为空", "reason": "invalid_source_id"}
        if not self._enabled:
            return {"success": False, "message": "插件未启用，无法调度来源", "reason": "plugin_disabled"}
        if not self._claim_source_dispatch_slot(source_id):
            return {"success": False, "message": "来源正在处理中，请稍后重试", "reason": "already_running"}

        def worker() -> None:
            try:
                self._submit_offline_source(source_id)
            except Exception as err:
                # daemon worker 的异常不能只落到 stderr：否则 UI 仍显示 dispatching，
                # source slot 虽释放但状态没有进入可恢复路径，形成“点了没反应”。
                try:
                    latest = dict((self._source_store().get("items") or {}).get(source_id) or {})
                except Exception:
                    latest = {}
                try:
                    if latest and str(latest.get("task_id") or "").strip():
                        # 服务端 task 已存在时绝不能因为本地 worker 异常再 create/retry；
                        # 保留 taskId 并回到 waiting，让下一轮只 poll 既有任务。
                        self._update_source(
                            source_id,
                            state="waiting",
                            last_error=f"后台执行异常，已保留 taskId 等待重新轮询：{str(err)[:360]}",
                            next_retry_at=0,
                        )
                    elif latest:
                        self._mark_offline_failure(latest, err)
                except Exception as state_err:
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【原生云添加】后台异常状态回写失败：source=%s error=%s",
                        source_id[:60],
                        str(state_err)[:260],
                    )
                self._plugin_log(
                    "EXCEPTION",
                    "【光鸭转存助手】【原生云添加】后台来源执行异常，已进入恢复路径：source=%s error=%s",
                    source_id[:60],
                    str(err)[:360],
                )
            finally:
                self._release_source_dispatch_slot(source_id)

        try:
            threading.Thread(
                target=worker,
                name=f"GuangYaOffline-{source_id[:8]}",
                daemon=True,
            ).start()
        except Exception as err:
            self._release_source_dispatch_slot(source_id)
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【原生云添加】启动来源调度线程失败：source=%s error=%s",
                source_id[:60],
                str(err)[:260],
            )
            return {"success": False, "message": f"启动后台调度失败：{str(err)[:120]}", "reason": "thread_start_failed"}
        return {"success": True, "message": "已进入光鸭原生云添加后台队列", "reason": "queued"}

    def _offline_tick(self) -> None:
        if not self._enabled or not self._external_auto_dispatch:
            return
        if not self._offline_lock.acquire(blocking=False):
            return
        try:
            now = time.time()
            rows = list(self._source_store()["items"].values())
            rows.sort(key=lambda row: str(row.get("updated_at") or ""))
            handled = 0
            for source in rows:
                if handled >= self._offline_batch_limit:
                    break
                if not isinstance(source, dict) or not source.get("enabled", True):
                    continue
                if str(source.get("type") or "") not in {"magnet", "ed2k"}:
                    continue
                if not bool(source.get("auto_dispatch", True)):
                    continue
                state = str(source.get("state") or "new")
                next_retry_at = float(source.get("next_retry_at") or 0)
                if state in SOURCE_PENDING_STATES:
                    if next_retry_at > now:
                        continue
                    source_id = str(source.get("id") or "")
                    if not self._claim_source_dispatch_slot(source_id):
                        continue
                    try:
                        self._submit_offline_source(source_id)
                    finally:
                        self._release_source_dispatch_slot(source_id)
                    handled += 1
                elif state in SOURCE_INFLIGHT_STATES:
                    source_id = str(source.get("id") or "")
                    if not self._claim_source_dispatch_slot(source_id):
                        continue
                    try:
                        self._poll_offline_source(source)
                    finally:
                        self._release_source_dispatch_slot(source_id)
                    handled += 1
        finally:
            self._offline_lock.release()

    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        if self._enabled and self._external_auto_dispatch:
            services.append({
                "id": "GuangYaTransferAssistantOfflineSources",
                "name": "光鸭转存助手 Magnet/ED2K 原生云添加任务",
                "trigger": "interval",
                "func": self._offline_tick,
                "kwargs": {"minutes": int(self._offline_poll_minutes or 2)},
            })
        return services

    def _resolve_source_subscription(
        self,
        subscribe_id: int = 0,
        title: str = "",
        year: str = "",
    ) -> Any:
        sid = int(subscribe_id or 0)
        if sid:
            return self._find_subscription(sid)
        normalized = _normalize_media_text(title)
        if not normalized:
            return None
        candidates = []
        for subscribe in self._list_subscriptions(None):
            name = _normalize_media_text(getattr(subscribe, "name", ""))
            if not name or name != normalized:
                continue
            if year and str(getattr(subscribe, "year", "") or "") not in ("", str(year)):
                continue
            candidates.append(subscribe)
        return candidates[0] if len(candidates) == 1 else None

    def api_source_list(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        rows = []
        for source in self._source_store()["items"].values():
            if not isinstance(source, dict):
                continue
            if sid and int(source.get("subscribe_id") or 0) != sid:
                continue
            row = dict(source)
            # 对外不需要暴露完整 URI 的 tracker/query 噪声；保留协议和稳定身份用于诊断。
            uri = str(row.get("uri") or "")
            row["uri_preview"] = uri[:180]
            rows.append(row)
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return {"success": True, "count": len(rows), "data": rows[:100]}

    def api_source_add(
        self,
        subscribe_id: int = 0,
        uri: str = "",
        label: str = "",
        dispatch: bool = True,
    ) -> Dict[str, Any]:
        try:
            row = self._upsert_source(
                int(subscribe_id or 0),
                uri,
                label=label,
                origin="manual",
                auto_dispatch=bool(dispatch),
            )
        except Exception as err:
            return {"success": False, "message": str(err)}
        if dispatch:
            dispatch_result = self._spawn_source_dispatch(str(row.get("id") or ""))
            if dispatch_result.get("success"):
                message = "来源已绑定订阅，并交给光鸭原生云添加"
            else:
                message = f"来源已绑定订阅，暂未进入后台队列：{dispatch_result.get('message')}"
            return {
                "success": True,
                "message": message,
                "data": row,
                "dispatch": dispatch_result,
            }
        return {
            "success": True,
            "message": "来源已绑定订阅",
            "data": row,
        }

    def api_source_delete(self, source_id: str = "") -> Dict[str, Any]:
        if not source_id:
            return {"success": False, "message": "source_id 不能为空"}
        if not self._delete_source(source_id):
            return {"success": False, "message": "来源不存在"}
        return {"success": True, "message": "来源绑定已删除"}

    def api_source_dispatch(self, source_id: str = "") -> Dict[str, Any]:
        source = self._source_store()["items"].get(str(source_id or ""))
        if not isinstance(source, dict):
            return {"success": False, "message": "来源不存在"}
        dispatch_result = self._spawn_source_dispatch(str(source_id))
        if not dispatch_result.get("success"):
            return dispatch_result
        return dispatch_result

    def api_source_retry(self, source_id: str = "") -> Dict[str, Any]:
        source = self._source_store()["items"].get(str(source_id or ""))
        if not isinstance(source, dict):
            return {"success": False, "message": "来源不存在"}
        current_state = str(source.get("state") or "new")
        if current_state in SOURCE_INFLIGHT_STATES:
            return {"success": False, "message": "来源正在处理中，无需手动重试", "reason": "already_inflight"}
        backup_fields = {
            "state": source.get("state"),
            "next_retry_at": source.get("next_retry_at", 0),
            "last_error": source.get("last_error", ""),
        }
        self._update_source(str(source_id), state="retry", next_retry_at=0, last_error="")
        dispatch_result = self._spawn_source_dispatch(str(source_id))
        if not dispatch_result.get("success"):
            self._update_source(str(source_id), **backup_fields)
            return dispatch_result
        return {"success": True, "message": "已请求光鸭原生任务重试", "dispatch": dispatch_result}

    def api_offline_refresh(self) -> Dict[str, Any]:
        threading.Thread(target=self._offline_tick, name="GuangYaOfflineRefresh", daemon=True).start()
        return {"success": True, "message": "光鸭云添加任务刷新已转入后台"}

    def api_viewing_ingest(
        self,
        subscribe_id: int = 0,
        uri: str = "",
        title: str = "",
        year: str = "",
        label: str = "",
        dispatch: bool = True,
    ) -> Dict[str, Any]:
        """MoviePilot“观影”订阅模式入口：把资源链接绑定到现有订阅。"""
        try:
            normalized = normalize_source_uri(uri)
        except Exception as err:
            return {"success": False, "message": str(err)}
        subscribe = self._resolve_source_subscription(subscribe_id, title, year)
        if not subscribe:
            return {
                "success": False,
                "message": "未唯一定位 MoviePilot 订阅；请传 subscribe_id，或传唯一匹配的 title/year",
            }
        try:
            row = self._upsert_source(
                int(getattr(subscribe, "id", 0) or 0),
                normalized["uri"],
                label=label,
                origin="viewing",
                auto_dispatch=bool(dispatch),
            )
        except Exception as err:
            return {"success": False, "message": str(err)}
        if dispatch:
            dispatch_result = self._spawn_source_dispatch(str(row.get("id") or ""))
            if dispatch_result.get("success"):
                message = f"观影来源已绑定 #{getattr(subscribe, 'id', 0)} {getattr(subscribe, 'name', '')}，使用光鸭原生云添加"
            else:
                message = (
                    f"观影来源已绑定 #{getattr(subscribe, 'id', 0)} {getattr(subscribe, 'name', '')}，"
                    f"暂未进入后台队列：{dispatch_result.get('message')}"
                )
            return {
                "success": True,
                "message": message,
                "data": row,
                "dispatch": dispatch_result,
            }
        return {
            "success": True,
            "message": f"观影来源已绑定 #{getattr(subscribe, 'id', 0)} {getattr(subscribe, 'name', '')}，使用光鸭原生云添加",
            "data": row,
        }

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        existing = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        extras = [
            {"path": "/sources", "endpoint": self.api_source_list, "methods": ["GET"], "summary": "列出 Magnet/ED2K 订阅来源"},
            {"path": "/source/add", "endpoint": self.api_source_add, "methods": ["POST"], "summary": "绑定 Magnet/ED2K 到 MoviePilot 订阅"},
            {"path": "/source/delete", "endpoint": self.api_source_delete, "methods": ["POST"], "summary": "删除订阅来源绑定"},
            {"path": "/source/dispatch", "endpoint": self.api_source_dispatch, "methods": ["POST"], "summary": "提交来源到光鸭原生云添加"},
            {"path": "/source/retry", "endpoint": self.api_source_retry, "methods": ["POST"], "summary": "重试光鸭原生云添加任务"},
            {"path": "/offline/refresh", "endpoint": self.api_offline_refresh, "methods": ["POST"], "summary": "后台刷新光鸭原生云添加任务"},
            {"path": "/viewing/ingest", "endpoint": self.api_viewing_ingest, "methods": ["POST"], "summary": "MoviePilot 观影订阅来源接入"},
        ]
        apis.extend(item for item in extras if item["path"] not in existing)
        return apis

    # ------------------------------------------------------------------
    # 状态页与自检
    # ------------------------------------------------------------------
    def _offline_source_summary(self) -> Dict[str, Any]:
        rows = [row for row in self._source_store()["items"].values() if isinstance(row, dict)]
        summary = {
            "total": len(rows),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "magnet": 0,
            "ed2k": 0,
        }
        for row in rows:
            source_type = str(row.get("type") or "")
            if source_type in ("magnet", "ed2k"):
                summary[source_type] += 1
            state = str(row.get("state") or "new")
            if state in SOURCE_PENDING_STATES:
                summary["pending"] += 1
            elif state in SOURCE_INFLIGHT_STATES:
                summary["running"] += 1
            elif state == "completed":
                summary["completed"] += 1
            elif state == "failed":
                summary["failed"] += 1
        return summary

    @staticmethod
    def _source_state_type(state: str) -> str:
        if state == "completed":
            return "success"
        if state == "failed":
            return "error"
        if state in SOURCE_INFLIGHT_STATES:
            return "info"
        if state in SOURCE_PENDING_STATES:
            return "warning"
        return "info"

    def get_page(self):
        existing_pages = list(super().get_page() or [])
        summary = self._offline_source_summary()
        rows = [dict(row) for row in self._source_store()["items"].values() if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)

        dashboard = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "光鸭转存 · 多来源控制台"},
                {
                    "component": "VCardText",
                    "text": (
                        "Telegram 光鸭分享、Magnet、ED2K 统一作为订阅来源。"
                        "Magnet/ED2K 直接进入光鸭云盘原生云添加，不经过 MoviePilot 下载器；"
                        "观影入口复用同一固定分流与订阅状态。"
                    ),
                },
                {
                    "component": "VRow",
                    "content": [
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "title": "来源总数", "text": str(summary["total"])}}]},
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "VAlert", "props": {"type": "warning", "variant": "tonal", "title": "等待 / 运行", "text": f"{summary['pending']} / {summary['running']}"}}]},
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "VAlert", "props": {"type": "success", "variant": "tonal", "title": "已完成", "text": str(summary["completed"])}}]},
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "VAlert", "props": {"type": "error" if summary["failed"] else "info", "variant": "tonal", "title": "失败", "text": str(summary["failed"])}}]},
                    ],
                },
                {
                    "component": "VCardActions",
                    "content": [{
                        "component": "VBtn",
                        "props": {"size": "small", "variant": "outlined", "prepend-icon": "mdi-cloud-sync-outline"},
                        "text": "刷新云添加任务",
                        "events": {
                            "click": {
                                "api": "plugin/GuangYaTransferAssistant/offline/refresh",
                                "method": "post",
                            }
                        },
                    }],
                },
            ],
        }

        source_cards: List[Dict[str, Any]] = []
        for row in rows[:20]:
            sid = int(row.get("subscribe_id") or 0)
            subscribe = self._find_subscription(sid)
            name = str(getattr(subscribe, "name", "") or row.get("resolved_name") or row.get("name") or "未命名")
            state = str(row.get("state") or "new")
            source_type = str(row.get("type") or "").upper()
            progress = int(row.get("progress") or 0)
            task_id = str(row.get("task_id") or "")
            error = str(row.get("last_error") or "")
            text = f"订阅 #{sid} · 状态 {state} · 进度 {progress}%"
            if task_id:
                text += f" · task {task_id}"
            if error:
                text += f" · {error}"
            source_cards.append({
                "component": "VAlert",
                "props": {
                    "type": self._source_state_type(state),
                    "variant": "tonal",
                    "class": "mb-2",
                    "title": f"{source_type} · {name}",
                    "text": text,
                },
            })
        sources_panel = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-3"},
            "content": [
                {"component": "VCardTitle", "text": "Magnet / ED2K 云添加任务"},
                {
                    "component": "VCardText",
                    "text": "任务状态来自光鸭 cloudcollection；服务重启后会继续按 taskId 轮询，不会重复创建离线任务。",
                },
                *source_cards,
            ],
        }

        advanced_header = {
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "class": "mb-3",
                "title": "高级诊断",
                "text": "下面保留固定分流、频道索引、转存任务与历史诊断，便于故障定位。",
            },
        }
        return [dashboard, sources_panel, advanced_header, *existing_pages]

    def _build_selfcheck(self) -> Dict[str, Any]:
        report = dict(super()._build_selfcheck())
        checks = list(report.get("checks") or [])
        source_count = int(self._offline_source_summary()["total"])
        try:
            client, api = self._get_guangya_runtime()
            native_ok = bool(client and api and callable(getattr(client, "_request", None)))
        except Exception:
            native_ok = False
        checks.append({
            "key": "native_offline",
            "label": "光鸭原生云添加",
            "ok": native_ok or source_count == 0,
            "detail": (
                "cloudcollection 可用，Magnet/ED2K 不经过 MoviePilot 下载器"
                if native_ok
                else ("尚未添加 Magnet/ED2K 来源" if source_count == 0 else "光鸭客户端不可用，云添加来源将等待恢复")
            ),
            "critical": bool(source_count),
        })
        report["checks"] = checks
        report["healthy"] = not any(item.get("critical") and not item.get("ok") for item in checks)
        report["offline_sources"] = self._offline_source_summary()
        report["build"] = self.build_id
        return report

    def _writeback_offline_candidate_diag_v209(
        self,
        source: Dict[str, Any],
        *,
        state: str,
        reason_code: str,
        stage: str,
        message: str = "",
    ) -> None:
        """Append terminal/pending diag to Resource Trace using action-carried ids (idempotent)."""
        if not isinstance(source, dict):
            return
        resource_trace = str(source.get("resource_trace_id") or "").strip()
        candidate_trace = str(source.get("candidate_trace_id") or "").strip()
        if not resource_trace and not candidate_trace:
            return
        # First terminal wins.
        terminal_key = f"diag_terminal::{candidate_trace or resource_trace}"
        if state in {"SUCCESS", "FAILED_FINAL", "FAILED_RETRYABLE", "SKIPPED", "SKIPPED_COMPLETE"}:
            if bool(source.get(terminal_key)):
                return
            try:
                self._update_source(str(source.get("id") or ""), **{terminal_key: True})
            except Exception:
                pass
        try:
            from .transfer_diag_v209 import make_diag
        except Exception:
            return
        row = make_diag(
            state=state,
            reason_code=reason_code,
            stage=stage,
            source=str(source.get("type") or "magnet"),
            message=str(message or "")[:360],
            resource_trace_id=resource_trace,
            candidate_trace_id=candidate_trace,
            subscription_run_id=str(source.get("subscription_run_id") or ""),
            sid=source.get("subscribe_id"),
            evidence={
                "source_id": str(source.get("id") or ""),
                "task_id": str(source.get("task_id") or ""),
                "identity": str(source.get("diag_identity") or source.get("identity") or "")[:120],
                "message_id": str(source.get("message_id") or ""),
            },
        )
        note = getattr(self, "_note_candidate_diag_v209", None)
        if callable(note):
            try:
                note(row)
                return
            except Exception:
                pass
        # Worker may run outside subscription TLS — write resource trace directly.
        tracer = getattr(self, "_resource_trace_v209", None)
        if callable(tracer) and resource_trace:
            try:
                tracer(
                    entry={
                        "resource_trace_id": resource_trace,
                        "message_id": str(source.get("message_id") or "-"),
                        "source_url": str(source.get("source_label") or ""),
                        "title": str(source.get("label") or ""),
                    },
                    state=f"{stage}/{state}",
                    reason=f"{reason_code}|{candidate_trace}|{str(message)[:120]}",
                    matched_sid=source.get("subscribe_id"),
                )
            except Exception:
                pass


    # ------------------------------------------------------------------
    # Consolidated native-offline safety boundary (formerly offline_safety_v180)
    # ------------------------------------------------------------------
    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        source = dict(self._source_store()["items"].get(str(source_id or "")) or {})
        task_id = str(source.get("task_id") or "").strip()
        state = str(source.get("state") or "new")
        if task_id:
            if state == "completed":
                return {"success": True, "message": "来源已完成", "data": source}
            if state in {"retry", "failed"}:
                return self._retry_offline_task(source)
            # 只要服务端任务已经存在，不论旧版本落下什么中间 state，都只能查询既有任务。
            return self._poll_offline_source(source)
        return self._submit_offline_source_base_v180(source_id)

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        before_attempts = int(source.get("attempts") or 0)
        result = self._poll_offline_source_base_v180(source)
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            return result

        task_status = data.get("task_status")
        try:
            task_status_code = int(task_status if task_status is not None else -1)
        except (TypeError, ValueError):
            task_status_code = -1

        # status=5 是光鸭明确返回的部分完成/失败，允许进入 retry/failed。
        # 其它失败若已有 taskId，则属于“查询暂不可用”，必须保留任务等待下轮，不得重新提交。
        if (
            str(source.get("task_id") or "").strip()
            and not bool(result.get("success"))
            and task_status_code != 5
        ):
            updated = self._update_source(
                str(source.get("id") or ""),
                state="waiting",
                attempts=before_attempts,
                next_retry_at=0,
                last_error=str(result.get("message") or data.get("last_error") or "任务状态查询暂不可用")[:500],
            ) or data
            return {
                **dict(result),
                "success": False,
                "message": str(result.get("message") or "任务状态查询暂不可用，已保留 taskId 等待恢复"),
                "data": updated,
            }
        return result

    @staticmethod
    def _source_public_view(source: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(source or {})
        raw_uri = str(row.pop("uri", "") or "")
        source_type = str(row.get("type") or "")
        identity = str(row.get("identity") or "")
        name = str(row.get("name") or row.get("resolved_name") or "")[:120]
        size = int(row.get("size") or 0)
        if source_type == "magnet":
            row["uri_preview"] = f"magnet:?xt=urn:btih:{identity}"
        elif source_type == "ed2k":
            row["uri_preview"] = f"ed2k://|file|{name}|{size}|{identity}|/"
        else:
            row["uri_preview"] = raw_uri[:120]
        return row

    def api_source_list(self, subscribe_id: int = 0) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        rows = []
        for source in self._source_store()["items"].values():
            if not isinstance(source, dict):
                continue
            if sid and int(source.get("subscribe_id") or 0) != sid:
                continue
            rows.append(self._source_public_view(source))
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return {"success": True, "count": len(rows), "data": rows[:100]}


__all__ = ["GuangYaMultiSourceMixin"]
