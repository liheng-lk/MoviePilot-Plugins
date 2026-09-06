"""v1.12.18：阻止失败/只读检查在光鸭云盘留下空目录。

本层只收口目录生命周期，不改变任何媒体身份、缺集、来源优先级或落盘规则。

核心原则：
1. ``GuangYaApi.get_folder`` 是 get-or-create，不能用于纯验证；恢复待落盘任务时只用
   ``get_item`` 查询目标目录，目录不存在即判定尚未落盘，绝不为了“检查”创建目录；
2. Magnet/ED2K 在第一次创建目标目录之前先完成 ``resolve_res`` 与文件选择；解析失败
   直接沿用原失败状态机，不创建任何目标目录；
3. 迅雷、光鸭分享以及 cloudcollection 真正写入前如果必须创建目录，只记录“本次调用前
   明确不存在”的目录；失败且没有服务端 taskId 时，才允许清理这些本次新建目录；
4. 清理前重新读取远端目录并列目录。已有目录、非空目录、读取失败、任务已经提交、
   ``/`` 与用户配置的保存根目录一律不删除；
5. 删除按最深层优先，只使用光鸭存储 API 的正常 delete，任何事实不确定都 fail closed。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .legacy import _normalize_config_path, _safe_relative_path
from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin


class GuangYaEmptyDirGuardV11218Mixin(GuangYaSearchRecallV11217Mixin):
    """为四种写盘来源提供统一的“只在真正写入时建目录”边界。"""

    plugin_version = "1.12.18"
    build_id = "20260906-r65"

    # ------------------------------------------------------------------
    # 线程本地目录事务
    # ------------------------------------------------------------------
    def _dir_guard_local_v11218(self) -> threading.local:
        local = getattr(self, "_empty_dir_guard_local_v11218", None)
        if local is None:
            local = threading.local()
            self._empty_dir_guard_local_v11218 = local
        return local

    def _dir_guard_current_v11218(self) -> Dict[str, Any] | None:
        return getattr(self._dir_guard_local_v11218(), "txn", None)

    def _dir_guard_begin_v11218(self, kind: str) -> Tuple[Dict[str, Any], bool]:
        local = self._dir_guard_local_v11218()
        current = getattr(local, "txn", None)
        if isinstance(current, dict):
            current["depth"] = int(current.get("depth") or 1) + 1
            return current, False
        txn: Dict[str, Any] = {
            "kind": str(kind or "write"),
            "depth": 1,
            "protected_root": _normalize_config_path(getattr(self, "_save_path", "/") or "/", "/"),
            "checked": set(),
            "created_candidates": set(),
            "unsafe": False,
        }
        local.txn = txn
        return txn, True

    def _dir_guard_end_v11218(self, txn: Dict[str, Any], owner: bool, *, cleanup: bool = False) -> None:
        if not owner:
            txn["depth"] = max(1, int(txn.get("depth") or 2) - 1)
            return
        try:
            if cleanup:
                self._cleanup_empty_dirs_v11218(txn)
        finally:
            local = self._dir_guard_local_v11218()
            if getattr(local, "txn", None) is txn:
                try:
                    delattr(local, "txn")
                except Exception:
                    local.txn = None

    @staticmethod
    def _cloud_path_v11218(value: Any) -> str:
        raw = str(value or "/").replace("\\", "/").strip()
        parts = [part.strip() for part in raw.split("/") if part.strip() and part.strip() not in {".", ".."}]
        return "/" + "/".join(parts) if parts else "/"

    def _record_create_path_v11218(self, path: Any) -> None:
        """在 get_folder 之前记录本次可能新建的目录；只记录保存根目录以下的后缀。"""
        txn = self._dir_guard_current_v11218()
        if not isinstance(txn, dict) or bool(txn.get("unsafe")):
            return
        normalized = self._cloud_path_v11218(path)
        protected = self._cloud_path_v11218(txn.get("protected_root") or "/")
        if normalized in {"/", protected}:
            return
        prefix = protected.rstrip("/")
        if protected != "/" and not normalized.startswith(prefix + "/"):
            txn["unsafe"] = True
            return

        relative = normalized[len(prefix):].strip("/") if protected != "/" else normalized.strip("/")
        if not relative:
            return
        _, api = self._get_guangya_runtime()
        if not api or not callable(getattr(api, "get_item", None)):
            # 无法证明目录之前不存在，则绝不能在失败后删除。
            txn["unsafe"] = True
            return

        current = protected if protected != "/" else ""
        for part in relative.split("/"):
            current = self._cloud_path_v11218((current.rstrip("/") + "/" + part) or "/")
            if current in {"/", protected} or current in txn["checked"]:
                continue
            txn["checked"].add(current)
            try:
                existing = api.get_item(Path(current))
            except Exception:
                txn["unsafe"] = True
                return
            if existing is None:
                txn["created_candidates"].add(current)
                continue
            if str(getattr(existing, "type", "dir") or "dir") != "dir":
                txn["unsafe"] = True
                return

    def _cleanup_empty_dirs_v11218(self, txn: Dict[str, Any]) -> int:
        """只删除本次前置检查明确不存在、现在仍确认为空的目录。"""
        if bool(txn.get("unsafe")):
            self._plugin_log("INFO", "【光鸭转存助手】【空目录保护v1.12.18】目录事实存在不确定性，本轮不执行自动回收")
            return 0
        candidates = sorted(
            {self._cloud_path_v11218(value) for value in (txn.get("created_candidates") or set())},
            key=lambda value: (value.count("/"), len(value)),
            reverse=True,
        )
        if not candidates:
            return 0
        protected = self._cloud_path_v11218(txn.get("protected_root") or "/")
        _, api = self._get_guangya_runtime()
        if not api:
            return 0
        get_item = getattr(api, "get_item", None)
        list_dir = getattr(api, "list", None)
        delete = getattr(api, "delete", None)
        if not callable(get_item) or not callable(list_dir) or not callable(delete):
            return 0

        removed = 0
        for path in candidates:
            if path in {"/", protected}:
                continue
            try:
                invalidate = getattr(api, "_invalidate_path_cache", None)
                if callable(invalidate):
                    invalidate(path)
                folder = get_item(Path(path))
                if folder is None:
                    continue
                if str(getattr(folder, "type", "") or "") != "dir":
                    continue
                children = list(list_dir(folder) or [])
            except Exception as err:
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【空目录保护v1.12.18】无法确认目录为空，保留：%s（%s）",
                    path,
                    str(err)[:180],
                )
                continue
            if children:
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【空目录保护v1.12.18】目录已出现文件/子目录，保留：%s",
                    path,
                )
                continue
            try:
                if bool(delete(folder)):
                    removed += 1
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【空目录保护v1.12.18】回收本次失败任务新建空目录：%s",
                        path,
                    )
            except Exception as err:
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【空目录保护v1.12.18】空目录回收失败，保留：%s（%s）",
                    path,
                    str(err)[:180],
                )
        return removed

    @staticmethod
    def _result_has_task_v11218(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        if str(result.get("task_id") or result.get("taskId") or "").strip():
            return True
        if any(str(value or "").strip() for value in (result.get("task_ids") or [])):
            return True
        data = result.get("data")
        if isinstance(data, dict):
            if str(data.get("task_id") or data.get("taskId") or "").strip():
                return True
            if any(str(value or "").strip() for value in (data.get("task_ids") or [])):
                return True
        return False

    # ------------------------------------------------------------------
    # Magnet / ED2K：resolve 在 get_folder 之前执行
    # ------------------------------------------------------------------
    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        source = dict(((self._source_store().get("items") or {}).get(source_id) or {}))
        needs_guard = (
            str(source.get("type") or "") in {"magnet", "ed2k"}
            and not str(source.get("task_id") or "").strip()
            and str(source.get("state") or "") != "completed"
        )
        if not needs_guard:
            return super()._submit_offline_source(source_id)

        txn, owner = self._dir_guard_begin_v11218("offline")
        txn["offline_source"] = source
        result: Dict[str, Any] = {}
        try:
            result = dict(super()._submit_offline_source(source_id) or {})
            cleanup = not bool(result.get("success")) and not self._result_has_task_v11218(result)
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner, cleanup=bool(locals().get("cleanup", False)))

    def _offline_target_parent(self, subscribe: Any) -> Tuple[str, str]:
        txn = self._dir_guard_current_v11218()
        if isinstance(txn, dict) and txn.get("kind") == "offline":
            source = dict(txn.get("offline_source") or {})
            if source and "offline_pre_resolved" not in txn:
                # 只在底层真正准备创建目录时预解析，因此前置安全层若已经拒绝来源，不会多打 resolve API。
                resolved = super()._resolve_offline_source(source, subscribe)
                txn["offline_pre_resolved"] = dict(resolved or {})
            self._record_create_path_v11218(self._target_path(subscribe))
        else:
            self._record_create_path_v11218(self._target_path(subscribe))
        return super()._offline_target_parent(subscribe)

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        txn = self._dir_guard_current_v11218()
        if isinstance(txn, dict) and txn.get("kind") == "offline" and "offline_pre_resolved" in txn:
            current_id = str((txn.get("offline_source") or {}).get("id") or "")
            source_id = str((source or {}).get("id") or "")
            if not current_id or not source_id or current_id == source_id:
                return dict(txn.get("offline_pre_resolved") or {})
        return super()._resolve_offline_source(source, subscribe)

    # ------------------------------------------------------------------
    # 迅雷：记录本次新建目标目录；有 taskId 时 fail closed 不删
    # ------------------------------------------------------------------
    def _xunlei_target_parent(self, subscribe: Any, relative_path: str) -> Tuple[str, str]:
        base = self._cloud_path_v11218(self._target_path(subscribe))
        self._record_create_path_v11218(base)
        relative = _safe_relative_path(relative_path)
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        if parent:
            self._record_create_path_v11218(base.rstrip("/") + "/" + parent)
        return super()._xunlei_target_parent(subscribe, relative_path)

    def _xunlei_import_json_file_v1117(
        self,
        subscribe: Any,
        obj: Dict[str, Any],
        source_row: Dict[str, Any],
    ) -> Dict[str, Any]:
        txn, owner = self._dir_guard_begin_v11218("xunlei")
        result: Dict[str, Any] = {}
        try:
            result = dict(super()._xunlei_import_json_file_v1117(subscribe, obj, source_row) or {})
            cleanup = not bool(result.get("success")) and not self._result_has_task_v11218(result)
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner, cleanup=bool(locals().get("cleanup", False)))

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        txn, owner = self._dir_guard_begin_v11218("xunlei")
        result: Dict[str, Any] = {}
        try:
            result = dict(super()._rapid_transfer_xunlei_file(subscribe, row) or {})
            cleanup = not bool(result.get("success")) and not self._result_has_task_v11218(result)
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner, cleanup=bool(locals().get("cleanup", False)))

    # ------------------------------------------------------------------
    # 光鸭分享：失败且未产生 taskId 才回收本次新建的空目录
    # ------------------------------------------------------------------
    def _restore_items(
        self,
        probe: Dict[str, Any],
        save_path: str,
        items: List[Dict[str, Any]],
        job_key: str = "",
    ) -> Dict[str, Any]:
        if not items:
            return super()._restore_items(probe, save_path, items, job_key=job_key)
        txn, owner = self._dir_guard_begin_v11218("share")
        base = _normalize_config_path(save_path, "/")
        for item in items:
            relative_parent = _safe_relative_path(item.get("target_parent") or "")
            target = (base.rstrip("/") + ("/" + relative_parent if relative_parent else "")) or "/"
            self._record_create_path_v11218(target)
        result: Dict[str, Any] = {}
        try:
            result = dict(super()._restore_items(probe, save_path, items, job_key=job_key) or {})
            cleanup = (
                not bool(result.get("success"))
                and not bool(result.get("pending_verification"))
                and not self._result_has_task_v11218(result)
            )
            return result
        except Exception:
            cleanup = True
            raise
        finally:
            self._dir_guard_end_v11218(txn, owner, cleanup=bool(locals().get("cleanup", False)))

    # ------------------------------------------------------------------
    # 待落盘复核是纯读操作：目标目录不存在时绝不通过 get_folder 创建它
    # ------------------------------------------------------------------
    def _verify_restored_items(self, save_path: str, items: List[Dict[str, Any]], max_try: int = 1) -> Dict[str, Any]:
        _, api = self._get_guangya_runtime()
        if not api:
            return {"success": False, "message": "光鸭云盘助手不可用", "verified_items": []}
        get_item = getattr(api, "get_item", None)
        if not callable(get_item):
            return {"success": False, "message": "光鸭存储运行时缺少只读目录查询能力", "verified_items": []}

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items or []:
            groups.setdefault(str(item.get("target_parent") or ""), []).append(item)
        verified: List[Dict[str, Any]] = []
        for relative_parent, group in groups.items():
            base = _normalize_config_path(save_path, "/")
            relative_parent = _safe_relative_path(relative_parent)
            normalized = (base.rstrip("/") + ("/" + relative_parent if relative_parent else "")) or "/"
            try:
                folder = get_item(Path(normalized))
            except Exception as err:
                return {"success": False, "message": str(err), "verified_items": verified}
            if folder is None:
                return {
                    "success": False,
                    "message": f"目标目录尚不存在：{normalized}",
                    "verified_items": verified,
                }
            parent_id = str(getattr(folder, "fileid", "") or "")
            result = self._verify_restored_group(
                api,
                parent_id,
                normalized,
                group,
                max_try=max_try,
                interval=0 if max_try <= 1 else 1.0,
            )
            if not result.get("success"):
                return {
                    "success": False,
                    "message": result.get("message") or "目标文件未确认可见",
                    "verified_items": verified,
                }
            verified.extend(result.get("verified_items") or group)
        return {"success": True, "verified_items": verified}


__all__ = ["GuangYaEmptyDirGuardV11218Mixin"]
