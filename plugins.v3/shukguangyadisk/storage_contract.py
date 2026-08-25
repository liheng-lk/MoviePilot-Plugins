"""MoviePilot V3 自定义存储模块合同。

V3 的 StorageChain 会优先通过插件 ``get_module()`` 调用自定义模块。若插件没有
接住自定义存储，请求会继续落到宿主 FileManager，而宿主只认识内置 StorageBase，
最终得到“Unsupported storage type”。本 mixin 同时兼容 V3 新存储名与 V2 历史名，
避免升级后已有整理任务继续引用 ``Shuk-光鸭云盘`` 时失效。

这里也是宿主存储契约的唯一兼容边界：MoviePilot 新增参数时优先在本层适配，
不继续修改 legacy 主体，避免存储协议与业务实现相互污染。
"""

from __future__ import annotations

from copy import copy as shallow_copy
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Optional


def _register_storage_selection(func: Callable) -> Callable:
    """在真实 MoviePilot 宿主中注册存储选择事件，独立单测时保持可导入。"""
    try:
        from app.core.event import eventmanager
        from app.schemas.types import ChainEventType
    except ImportError:
        return func
    return eventmanager.register(ChainEventType.StorageOperSelection)(func)


class V3StorageContractMixin:
    """为光鸭自定义存储补齐 MoviePilot V3 合同及历史存储名兼容。"""

    @staticmethod
    def _action_name(action: Any) -> str:
        """兼容 StorageAction 枚举和直接字符串。"""
        value = getattr(action, "value", action)
        return str(value or "").strip()

    @staticmethod
    def _dump_model(value: Any) -> Any:
        """把 Pydantic 模型转换为可 JSON 序列化对象。"""
        if value is None:
            return {}
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump()
        if isinstance(value, (dict, list, str, int, float, bool)):
            return value
        return dict(value) if hasattr(value, "keys") else value

    def _storage_names(self) -> set[str]:
        """返回当前 V3 名称和仍可能存在于历史任务中的 V2 名称。"""
        return {
            name
            for name in (
                str(getattr(self, "_disk_name", "") or "").strip(),
                str(getattr(self, "_legacy_disk_name", "") or "").strip(),
            )
            if name
        }

    def _matches_storage(self, storage: Any) -> bool:
        return str(storage or "").strip() in self._storage_names()

    def _normalize_storage(self, storage: Any) -> Any:
        """历史名只用于识别；进入既有上传实现前统一转换为 V3 当前名。"""
        return self._disk_name if self._matches_storage(storage) else storage

    def _normalize_fileitem(self, fileitem: Any) -> Any:
        """复制 FileItem 并把历史 storage 名转换为 V3 当前名，不修改调用方对象。"""
        if fileitem is None:
            return None
        storage = getattr(fileitem, "storage", None)
        if storage == self._disk_name or not self._matches_storage(storage):
            return fileitem

        model_copy = getattr(fileitem, "model_copy", None)
        if callable(model_copy):
            return model_copy(update={"storage": self._disk_name})

        legacy_copy = getattr(fileitem, "copy", None)
        if callable(legacy_copy):
            try:
                return legacy_copy(update={"storage": self._disk_name})
            except TypeError:
                pass

        clone = shallow_copy(fileitem)
        setattr(clone, "storage", self._disk_name)
        return clone

    def _wrap_fileitem_handler(self, handler: Callable) -> Callable:
        @wraps(handler)
        def wrapped(*args: Any, **kwargs: Any):
            if args:
                first = args[0]
                storage = getattr(first, "storage", None)
                if storage is not None:
                    if not self._matches_storage(storage):
                        return None
                    args = (self._normalize_fileitem(first), *args[1:])
            elif "fileitem" in kwargs:
                storage = getattr(kwargs["fileitem"], "storage", None)
                if storage is not None:
                    if not self._matches_storage(storage):
                        return None
                    kwargs = dict(kwargs)
                    kwargs["fileitem"] = self._normalize_fileitem(kwargs["fileitem"])
            return handler(*args, **kwargs)

        return wrapped

    def _wrap_storage_handler(self, handler: Callable) -> Callable:
        @wraps(handler)
        def wrapped(*args: Any, **kwargs: Any):
            if args:
                storage = args[0]
                if not self._matches_storage(storage):
                    return None
                args = (self._disk_name, *args[1:])
            elif "storage" in kwargs:
                if not self._matches_storage(kwargs["storage"]):
                    return None
                kwargs = dict(kwargs)
                kwargs["storage"] = self._disk_name
            return handler(*args, **kwargs)

        return wrapped

    def snapshot_storage(
        self,
        storage: str,
        path: Path,
        last_snapshot_time: float = None,
        max_depth: int = 5,
        previous_snapshot: Optional[Dict[str, Dict]] = None,
    ) -> Optional[Dict[str, Dict]]:
        """实现 MoviePilot V3 当前完整快照契约。

        MoviePilot 现在会把 ``previous_snapshot`` 作为关键字参数传给自定义存储。
        v3.3.0 仍继承 legacy 四参数实现，因此会在宿主调用阶段直接抛出 TypeError。

        本实现与 MoviePilot ``StorageBase.snapshot`` 语义对齐：
        - 从上一轮完整快照起步，保留未重新遍历的增量目录；
        - 根目录每轮至少列举一次，用于清理已经移动/删除的直接子项；
        - 子目录仍可按 modify_time 跳过，降低远端 API 压力；
        - 文件记录包含 size/modify_time/fileid/type，供宿主正确比较变化。
        """
        if not self._matches_storage(storage):
            return None
        if not getattr(self, "_guangya_api", None):
            return {}

        root_path = PurePosixPath(Path(path).as_posix())
        files_info: Dict[str, Dict] = {}
        for file_path, file_info in (previous_snapshot or {}).items():
            try:
                if PurePosixPath(str(file_path)).is_relative_to(root_path):
                    files_info[str(file_path)] = dict(file_info or {})
            except (TypeError, ValueError):
                continue

        def remove_deleted_children(directory_item: Any, sub_files: list[Any]) -> None:
            directory_path = PurePosixPath(str(getattr(directory_item, "path", "") or "/"))
            child_paths = {
                PurePosixPath(str(getattr(sub_file, "path", "") or ""))
                for sub_file in sub_files
                if getattr(sub_file, "path", None)
            }
            for old_file_path in list(files_info):
                try:
                    relative_path = PurePosixPath(old_file_path).relative_to(directory_path)
                except ValueError:
                    continue
                if not relative_path.parts:
                    continue
                direct_child = directory_path / relative_path.parts[0]
                if direct_child not in child_paths:
                    files_info.pop(old_file_path, None)

        def snapshot_item(fileitem: Any, current_depth: int = 0) -> None:
            try:
                if getattr(fileitem, "type", None) == "dir":
                    if current_depth >= max_depth:
                        return
                    if (
                        current_depth > 0
                        and bool(getattr(self, "snapshot_check_folder_modtime", True))
                        and last_snapshot_time
                        and getattr(fileitem, "modify_time", None)
                        and fileitem.modify_time <= last_snapshot_time
                    ):
                        return

                    sub_files = self._guangya_api.list(fileitem)
                    if sub_files is None:
                        return
                    sub_files = list(sub_files)
                    remove_deleted_children(fileitem, sub_files)
                    for sub_file in sub_files:
                        snapshot_item(sub_file, current_depth + 1)
                    return

                file_path = str(getattr(fileitem, "path", "") or "")
                if not file_path:
                    return
                files_info[file_path] = {
                    "size": int(getattr(fileitem, "size", 0) or 0),
                    "modify_time": getattr(fileitem, "modify_time", 0) or 0,
                    "fileid": getattr(fileitem, "fileid", None),
                    "type": getattr(fileitem, "type", "file") or "file",
                }
            except Exception:
                # 快照单项异常不应摧毁整轮快照；宿主下一轮仍会继续对账。
                return

        root_item = self._guangya_api.get_item(Path(path))
        if not root_item:
            return {}
        snapshot_item(root_item)
        return files_info

    def _v3_storage_helper(self):
        """延迟导入稳定 SDK，便于脱离 MoviePilot 宿主做合同单测。"""
        from app.sdk.services import StorageHelper

        return StorageHelper()

    def get_module(self) -> Dict[str, Any]:
        """补齐 V3 管理入口，并为旧存储名包一层兼容转换。"""
        modules = dict(super().get_module() or {})

        for name in (
            "list_files",
            "any_files",
            "download_file",
            "upload_file",
            "delete_file",
            "rename_file",
            "get_parent_item",
            "create_folder",
            "exists",
            "get_item",
        ):
            handler = modules.get(name)
            if callable(handler):
                modules[name] = self._wrap_fileitem_handler(handler)

        for name in (
            "get_file_item",
            "snapshot_storage",
            "storage_usage",
            "support_transtype",
        ):
            handler = modules.get(name)
            if callable(handler):
                modules[name] = self._wrap_storage_handler(handler)

        modules["storage_manage"] = self.storage_manage
        modules["get_folder"] = self.get_folder
        return modules

    @_register_storage_selection
    def storage_oper_selection(self, event: Any):
        """新旧存储名都返回光鸭存储操作对象，兼容历史整理任务。"""
        if not getattr(self, "_enabled", False):
            return
        event_data = getattr(event, "event_data", None)
        if event_data and self._matches_storage(getattr(event_data, "storage", None)):
            event_data.storage_oper = self._guangya_api

    def get_folder(self, storage: str, path: Path):
        """适配 V3 ``StorageChain.get_folder(storage, path)``，兼容历史名称。"""
        if not self._matches_storage(storage):
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.get_folder(path)

    def _action_response(self, result: Any, default_message: str = "") -> Dict[str, Any]:
        """把插件原有登录动作结果转换为 V3 storage_manage envelope。"""
        if isinstance(result, dict):
            success = bool(result.get("success"))
            message = str(result.get("message") or default_message or "")
            return {
                "success": success,
                "message": message,
                "data": result if success else None,
            }
        return {
            "success": bool(result),
            "message": default_message if not result else "",
            "data": result if result else None,
        }

    def storage_manage(
        self,
        storage: str,
        action: Any,
        **params: Any,
    ) -> Optional[Dict[str, Any]]:
        """处理 V3 网盘统一管理动作，并短路新旧光鸭存储名。"""
        if not self._matches_storage(storage):
            return None

        action_name = self._action_name(action)

        if action_name == "support_transtype":
            return {
                "success": True,
                "message": "",
                "data": {"transtype": self.support_transtype(self._disk_name) or {}},
            }

        if action_name == "usage":
            if not self._guangya_api:
                return {
                    "success": False,
                    "message": "光鸭云盘助手尚未初始化或未登录",
                    "data": {},
                }
            try:
                usage = self.storage_usage(self._disk_name)
                return {
                    "success": True,
                    "message": "",
                    "data": self._dump_model(usage),
                }
            except Exception as err:
                return {
                    "success": False,
                    "message": f"获取光鸭云盘空间信息失败: {err}",
                    "data": {},
                }

        if action_name == "get_config":
            conf = self._v3_storage_helper().get_storage(self._disk_name)
            return {
                "success": True,
                "message": "",
                "data": self._dump_model(conf),
            }

        if action_name == "save_config":
            conf = params.get("conf") or {}
            self._v3_storage_helper().set_storage(self._disk_name, conf)
            return {"success": True, "message": "", "data": {}}

        if action_name == "reset_config":
            self._v3_storage_helper().reset_storage(self._disk_name)
            return {"success": True, "message": "", "data": {}}

        if action_name == "generate_qrcode":
            return self._action_response(self.get_qrcode(), "获取二维码失败")

        if action_name == "check_login":
            return self._action_response(self.poll_login(), "登录状态检查失败")

        if action_name == "logout":
            return self._action_response(self.logout(), "退出登录失败")

        if action_name in {"check", "test_connection"}:
            if not self._enabled or not self._guangya_api:
                return {
                    "success": False,
                    "message": "光鸭云盘助手未启用或未登录",
                    "data": {"available": False},
                }
            try:
                root = self._guangya_api.get_item(Path("/"))
                available = root is not None
                return {
                    "success": available,
                    "message": "" if available else "无法读取光鸭云盘根目录",
                    "data": {"available": available},
                }
            except Exception as err:
                return {
                    "success": False,
                    "message": f"光鸭云盘连接测试失败: {err}",
                    "data": {"available": False},
                }

        if action_name == "generate_auth_url":
            return {
                "success": False,
                "message": "光鸭云盘使用扫码或短信登录，不使用 OAuth2 授权地址",
                "data": None,
            }

        return {
            "success": False,
            "message": f"光鸭云盘助手暂不支持存储管理动作：{action_name or 'unknown'}",
            "data": None,
        }
