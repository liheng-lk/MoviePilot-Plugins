"""v1.12.19：为异步写盘任务持久化空目录租约并在终态安全回收。

v1.12.18 只能够在一次同步调用内知道“哪些目录在调用前不存在”。一旦服务端已经返回
``taskId``，或光鸭分享进入 ``pending_verification``，线程本地事务结束后这份事实就会丢失；
后续任务异步失败、完成但实际 0 文件、插件重启，都可能留下永久空目录。

本层不改变任何资源检索、媒体身份、缺集、Episode Fence 或来源优先级。它只把 v1.12.18
已经证明为“本次新建”的目录持久化为 lease，并在明确终态后重新读取远端目录树：
- 发现任意文件：仅释放 lease，绝不删除；
- 目录/列表事实未知：保留 lease，fail closed；
- 仍有其它活跃 lease 覆盖同一路径：不删除；
- 明确终态、经过可见性宽限期且整棵新建目录树仍 0 文件：最深层优先回收；
- 配置保存根、``/``、调用前已存在目录永远不进入 lease。
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .empty_dir_guard_v11218 import GuangYaEmptyDirGuardV11218Mixin


class GuangYaEmptyDirLeaseV11219Mixin(GuangYaEmptyDirGuardV11218Mixin):
    """跨异步任务/进程重启保留目录创建事实，终态后只回收确认 0 文件的新目录。"""

    plugin_version = "1.12.19"
    build_id = "20260906-r66"
    _empty_dir_lease_data_v11219 = "empty_dir_leases_v11219"
    _empty_dir_lease_grace_v11219 = 120
    _empty_dir_share_grace_v11219 = 300
    _empty_dir_lease_max_v11219 = 600

    def init_plugin(self, config: dict = None) -> None:
        self._empty_dir_lease_lock_v11219 = threading.RLock()
        return super().init_plugin(config)

    def _lease_lock_v11219(self) -> threading.RLock:
        lock = getattr(self, "_empty_dir_lease_lock_v11219", None)
        if lock is None:
            lock = threading.RLock()
            self._empty_dir_lease_lock_v11219 = lock
        return lock

    def _lease_store_v11219(self) -> Dict[str, Any]:
        raw = self.get_data(self._empty_dir_lease_data_v11219) or {}
        items = raw.get("items") if isinstance(raw, dict) else None
        return {"schema": 1, "items": dict(items or {})}

    def _save_lease_store_v11219(self, store: Dict[str, Any]) -> None:
        payload = {"schema": 1, "updated_at": time.time(), "items": dict((store or {}).get("items") or {})}
        if len(payload["items"]) > int(self._empty_dir_lease_max_v11219 or 600):
            ordered = sorted(
                payload["items"].items(),
                key=lambda pair: float((pair[1] or {}).get("updated_at") or (pair[1] or {}).get("created_at") or 0),
                reverse=True,
            )[: int(self._empty_dir_lease_max_v11219 or 600)]
            payload["items"] = dict(ordered)
        self.save_data(self._empty_dir_lease_data_v11219, payload)

    @staticmethod
    def _task_ids_v11219(result: Any) -> List[str]:
        found: List[str] = []
        if not isinstance(result, dict):
            return found
        for container in (result, result.get("data") if isinstance(result.get("data"), dict) else {}):
            if not isinstance(container, dict):
                continue
            for key in ("task_id", "taskId"):
                value = str(container.get(key) or "").strip()
                if value:
                    found.append(value)
            for key in ("task_ids", "taskIds"):
                values = container.get(key) or []
                if isinstance(values, (list, tuple, set)):
                    found.extend(str(value or "").strip() for value in values if str(value or "").strip())
        return list(dict.fromkeys(found))

    @staticmethod
    def _lease_key_v11219(kind: str, owner: str) -> str:
        return f"{str(kind or 'write').strip()}:{str(owner or '').strip()}"

    @staticmethod
    def _share_owner_v11219(job_key: str, save_path: str, items: Iterable[Dict[str, Any]]) -> str:
        if str(job_key or "").strip():
            return str(job_key).strip()
        raw = str(save_path or "") + "|" + "|".join(
            sorted(
                str((item or {}).get("effective_path") or (item or {}).get("relative_path") or (item or {}).get("name") or "")
                for item in (items or [])
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _lease_paths_v11219(self, txn: Dict[str, Any]) -> List[str]:
        protected = self._cloud_path_v11218((txn or {}).get("protected_root") or "/")
        rows = []
        for raw in (txn or {}).get("created_candidates") or set():
            path = self._cloud_path_v11218(raw)
            if path in {"/", protected}:
                continue
            prefix = protected.rstrip("/")
            if protected != "/" and not path.startswith(prefix + "/"):
                continue
            rows.append(path)
        return sorted(set(rows), key=lambda value: (value.count("/"), len(value)))

    def _persist_lease_v11219(
        self,
        txn: Dict[str, Any],
        *,
        kind: str,
        owner: str,
        task_ids: Iterable[str] = (),
        subscribe_id: int = 0,
        terminal_hint: bool = False,
    ) -> str:
        paths = self._lease_paths_v11219(txn)
        owner = str(owner or "").strip()
        if not paths or not owner:
            return ""
        key = self._lease_key_v11219(kind, owner)
        now = time.time()
        with self._lease_lock_v11219():
            store = self._lease_store_v11219()
            previous = dict(store["items"].get(key) or {})
            record = {
                **previous,
                "kind": str(kind or "write"),
                "owner": owner,
                "paths": sorted(set([*list(previous.get("paths") or []), *paths])),
                "protected_root": self._cloud_path_v11218(txn.get("protected_root") or "/"),
                "task_ids": list(dict.fromkeys([*list(previous.get("task_ids") or []), *[str(v) for v in task_ids if str(v or "").strip()]])),
                "subscribe_id": int(subscribe_id or previous.get("subscribe_id") or 0),
                "created_at": float(previous.get("created_at") or now),
                "updated_at": now,
                "terminal_hint": bool(terminal_hint or previous.get("terminal_hint")),
                "terminal_seen_at": float(previous.get("terminal_seen_at") or 0),
            }
            store["items"][key] = record
            self._save_lease_store_v11219(store)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【空目录租约v1.12.19】持久化 kind=%s owner=%s paths=%s task=%s",
            kind,
            owner[:24],
            len(paths),
            ",".join(record.get("task_ids") or [])[:120] or "-",
        )
        return key

    def _drop_lease_v11219(self, key: str, reason: str = "") -> None:
        key = str(key or "").strip()
        if not key:
            return
        with self._lease_lock_v11219():
            store = self._lease_store_v11219()
            if key not in store["items"]:
                return
            store["items"].pop(key, None)
            self._save_lease_store_v11219(store)
        if reason:
            self._plugin_log("INFO", "【光鸭转存助手】【空目录租约v1.12.19】释放 %s：%s", key[:80], reason[:180])

    @staticmethod
    def _path_overlap_v11219(left: str, right: str) -> bool:
        left = str(left or "/").rstrip("/") or "/"
        right = str(right or "/").rstrip("/") or "/"
        return left == right or left.startswith(right + "/") or right.startswith(left + "/")

    def _other_live_lease_overlaps_v11219(self, current_key: str, paths: Iterable[str]) -> bool:
        store = self._lease_store_v11219()
        wanted = [self._cloud_path_v11218(path) for path in paths]
        for key, raw in store["items"].items():
            if str(key) == str(current_key) or not isinstance(raw, dict):
                continue
            # 其它尚未进入终态宽限的 lease 视为活跃写入所有者。
            if float(raw.get("terminal_seen_at") or 0) > 0 or bool(raw.get("terminal_hint")):
                continue
            for left in wanted:
                if any(self._path_overlap_v11219(left, self._cloud_path_v11218(right)) for right in (raw.get("paths") or [])):
                    return True
        return False

    def _lease_roots_v11219(self, paths: Iterable[str]) -> List[str]:
        ordered = sorted({self._cloud_path_v11218(path) for path in paths}, key=lambda value: (value.count("/"), len(value)))
        roots: List[str] = []
        for path in ordered:
            if any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots):
                continue
            roots.append(path)
        return roots

    def _scan_empty_tree_v11219(self, api: Any, root: str) -> Tuple[str, List[Any]]:
        """返回 missing/empty/occupied/unknown；empty 时附带可安全删除的目录对象。"""
        get_item = getattr(api, "get_item", None)
        list_dir = getattr(api, "list", None)
        if not callable(get_item) or not callable(list_dir):
            return "unknown", []
        invalidate = getattr(api, "_invalidate_path_cache", None)
        try:
            if callable(invalidate):
                invalidate(root)
            item = get_item(Path(root))
        except Exception:
            return "unknown", []
        if item is None:
            return "missing", []
        if str(getattr(item, "type", "") or "") != "dir":
            return "occupied", []

        dirs: List[Any] = []
        stack: List[Any] = [item]
        visited = set()
        while stack:
            folder = stack.pop()
            folder_id = str(getattr(folder, "fileid", "") or getattr(folder, "path", "") or id(folder))
            if folder_id in visited:
                continue
            visited.add(folder_id)
            dirs.append(folder)
            try:
                children = list(list_dir(folder) or [])
            except Exception:
                return "unknown", []
            for child in children:
                if str(getattr(child, "type", "") or "") == "dir":
                    stack.append(child)
                else:
                    return "occupied", []
        return "empty", dirs

    def _reclaim_lease_v11219(self, key: str, record: Dict[str, Any]) -> str:
        paths = [self._cloud_path_v11218(path) for path in (record.get("paths") or [])]
        protected = self._cloud_path_v11218(record.get("protected_root") or "/")
        roots = [path for path in self._lease_roots_v11219(paths) if path not in {"/", protected}]
        if not roots:
            return "missing"
        if self._other_live_lease_overlaps_v11219(key, roots):
            return "busy"
        _, api = self._get_guangya_runtime()
        if not api or not callable(getattr(api, "delete", None)):
            return "unknown"

        all_dirs: List[Any] = []
        saw_existing = False
        for root in roots:
            state, dirs = self._scan_empty_tree_v11219(api, root)
            if state == "occupied":
                return "occupied"
            if state == "unknown":
                return "unknown"
            if state == "empty":
                saw_existing = True
                all_dirs.extend(dirs)

        if not saw_existing:
            return "missing"

        # 根目录在本轮前明确不存在，因此其下面当前仍为空的目录也一定是在之后创建；
        # 但仍按最深层优先逐个 delete，并在每次 delete 前再次由存储 API 校验为空。
        all_dirs.sort(
            key=lambda item: str(getattr(item, "path", "") or "").count("/"),
            reverse=True,
        )
        removed = 0
        for folder in all_dirs:
            path = self._cloud_path_v11218(getattr(folder, "path", "") or "/")
            if path in {"/", protected}:
                continue
            try:
                if list(getattr(api, "list")(folder) or []):
                    return "occupied"
                if bool(getattr(api, "delete")(folder)):
                    removed += 1
            except Exception:
                return "unknown"
        if removed:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【空目录租约v1.12.19】终态 0 文件，回收空目录树：key=%s removed=%s",
                key[:80],
                removed,
            )
        return "removed"

    def _mark_terminal_v11219(self, key: str, record: Dict[str, Any]) -> Dict[str, Any]:
        if float(record.get("terminal_seen_at") or 0) > 0:
            return record
        now = time.time()
        updated = dict(record)
        updated["terminal_seen_at"] = now
        updated["updated_at"] = now
        with self._lease_lock_v11219():
            store = self._lease_store_v11219()
            if key in store["items"]:
                store["items"][key] = updated
                self._save_lease_store_v11219(store)
        return updated

    def _reconcile_empty_dir_leases_v11219(self) -> None:
        with self._lease_lock_v11219():
            snapshot = self._lease_store_v11219()
        if not snapshot["items"]:
            return
        sources = ((self._source_store() or {}).get("items") or {}) if callable(getattr(self, "_source_store", None)) else {}
        jobs = self.get_data("transfer_jobs") or {}
        now = time.time()

        for key, raw in list(snapshot["items"].items()):
            if not isinstance(raw, dict):
                self._drop_lease_v11219(str(key), "非法 lease 记录")
                continue
            record = dict(raw)
            kind = str(record.get("kind") or "")
            owner = str(record.get("owner") or "")
            terminal = bool(record.get("terminal_hint"))
            release_without_delete = False
            grace = max(0, int(getattr(self, "_empty_dir_lease_grace_v11219", 120)))

            if kind == "offline":
                source = dict(sources.get(owner) or {})
                state = str(source.get("state") or "")
                if state == "completed":
                    terminal = True
                elif state == "failed":
                    terminal = True
                elif state:
                    terminal = False
            elif kind == "share":
                job = dict(jobs.get(owner) or {})
                status = str(job.get("status") or "")
                if status in {"verified", "synced", "partial"}:
                    release_without_delete = True
                elif status == "cancelled":
                    # 人工忽略不等于服务端任务已取消；不能为了清目录破坏可能仍在落盘的任务。
                    release_without_delete = True
                elif status == "failed":
                    terminal = True
                elif status == "verifying":
                    # restore_share 已经经过 task_confirmed，随后 30 次目标可见性复核仍失败；
                    # 再给较长宽限期，之后仍 0 文件才回收。
                    terminal = True
                    grace = max(0, int(getattr(self, "_empty_dir_share_grace_v11219", 300)))
                elif status:
                    terminal = False
            elif kind == "xunlei":
                terminal = bool(record.get("terminal_hint"))

            if release_without_delete:
                self._drop_lease_v11219(str(key), f"终态已确认写入/人工忽略 kind={kind}")
                continue
            if not terminal:
                continue

            record = self._mark_terminal_v11219(str(key), record)
            terminal_seen_at = float(record.get("terminal_seen_at") or 0)
            terminal_age = max(0.0, time.time() - terminal_seen_at)
            if grace > 0 and terminal_age < grace:
                continue
            outcome = self._reclaim_lease_v11219(str(key), record)
            if outcome in {"removed", "missing", "occupied"}:
                self._drop_lease_v11219(str(key), f"reconcile={outcome}")

    # ------------------------------------------------------------------
    # 四条写盘路径：用外层 txn 接住 v1.12.18 的 created_candidates，并跨调用持久化。
    # ------------------------------------------------------------------
    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        source = dict((((self._source_store() or {}).get("items") or {}).get(source_id) or {}))
        needs_lease = (
            str(source.get("type") or "") in {"magnet", "ed2k"}
            and not str(source.get("task_id") or "").strip()
            and str(source.get("state") or "") != "completed"
        )
        if not needs_lease:
            return super()._submit_offline_source(source_id)

        txn, owner_txn = self._dir_guard_begin_v11218("offline")
        txn["offline_source"] = source
        result: Dict[str, Any] = {}
        cleanup = False
        try:
            result = dict(super()._submit_offline_source(source_id) or {})
            latest = dict(result.get("data") or {}) if isinstance(result.get("data"), dict) else {}
            task_ids = self._task_ids_v11219(result)
            task_id = str(latest.get("task_id") or source.get("task_id") or "").strip()
            if task_id and task_id not in task_ids:
                task_ids.append(task_id)
            if task_ids:
                self._persist_lease_v11219(
                    txn,
                    kind="offline",
                    owner=source_id,
                    task_ids=task_ids,
                    subscribe_id=int(source.get("subscribe_id") or 0),
                )
            elif not bool(result.get("success")):
                cleanup = True
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner_txn, cleanup=cleanup)

    def _restore_items(
        self,
        probe: Dict[str, Any],
        save_path: str,
        items: List[Dict[str, Any]],
        job_key: str = "",
    ) -> Dict[str, Any]:
        if not items:
            return super()._restore_items(probe, save_path, items, job_key=job_key)
        txn, owner_txn = self._dir_guard_begin_v11218("share")
        result: Dict[str, Any] = {}
        cleanup = False
        owner = self._share_owner_v11219(job_key, save_path, items)
        try:
            result = dict(super()._restore_items(probe, save_path, items, job_key=job_key) or {})
            task_ids = self._task_ids_v11219(result)
            pending = bool(result.get("pending_verification")) or bool(task_ids)
            if pending:
                self._persist_lease_v11219(txn, kind="share", owner=owner, task_ids=task_ids)
            elif not bool(result.get("success")):
                cleanup = True
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner_txn, cleanup=cleanup)

    def _xunlei_import_json_file_v1117(
        self,
        subscribe: Any,
        obj: Dict[str, Any],
        source_row: Dict[str, Any],
    ) -> Dict[str, Any]:
        txn, owner_txn = self._dir_guard_begin_v11218("xunlei")
        result: Dict[str, Any] = {}
        cleanup = False
        try:
            result = dict(super()._xunlei_import_json_file_v1117(subscribe, obj, source_row) or {})
            task_ids = self._task_ids_v11219(result)
            if not bool(result.get("success")) and task_ids:
                path = str(((obj.get("files") or [{}])[0]).get("path") or source_row.get("path") or "")
                owner = task_ids[0] or hashlib.sha256(path.encode("utf-8")).hexdigest()
                self._persist_lease_v11219(
                    txn,
                    kind="xunlei",
                    owner=owner,
                    task_ids=task_ids,
                    terminal_hint=True,
                )
            elif not bool(result.get("success")):
                cleanup = True
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner_txn, cleanup=cleanup)

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        txn, owner_txn = self._dir_guard_begin_v11218("xunlei")
        result: Dict[str, Any] = {}
        cleanup = False
        try:
            result = dict(super()._rapid_transfer_xunlei_file(subscribe, row) or {})
            task_ids = self._task_ids_v11219(result)
            if not bool(result.get("success")) and task_ids:
                path = str(row.get("path") or row.get("name") or "")
                owner = task_ids[0] or hashlib.sha256(path.encode("utf-8")).hexdigest()
                self._persist_lease_v11219(
                    txn,
                    kind="xunlei",
                    owner=owner,
                    task_ids=task_ids,
                    terminal_hint=True,
                )
            elif not bool(result.get("success")):
                cleanup = True
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner_txn, cleanup=cleanup)

    def _set_job_state(self, job_key: str, status: str, **fields: Any) -> None:
        result = super()._set_job_state(job_key, status, **fields)
        if str(status or "") in {"verified", "synced", "partial", "cancelled"}:
            self._drop_lease_v11219(self._lease_key_v11219("share", str(job_key or "")), f"job={status}")
        return result

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(super()._poll_offline_source(source) or {})
        # 不在轮询调用内直接删除；只更新 source 状态，统一交给周期 reconciler 做二次远端确认。
        self._reconcile_empty_dir_leases_v11219()
        return result

    def _offline_tick(self) -> None:
        try:
            return super()._offline_tick()
        finally:
            self._reconcile_empty_dir_leases_v11219()

    def get_service(self) -> List[Dict[str, Any]]:
        services = list(super().get_service() or [])
        if bool(getattr(self, "_enabled", False)) and not any(
            str((row or {}).get("id") or "") == "GuangYaTransferAssistantEmptyDirLeaseV11219"
            for row in services
            if isinstance(row, dict)
        ):
            services.append({
                "id": "GuangYaTransferAssistantEmptyDirLeaseV11219",
                "name": "光鸭转存助手空目录终态回收",
                "trigger": "interval",
                "func": self._reconcile_empty_dir_leases_v11219,
                "kwargs": {"minutes": 2},
            })
        return services


__all__ = ["GuangYaEmptyDirLeaseV11219Mixin"]
