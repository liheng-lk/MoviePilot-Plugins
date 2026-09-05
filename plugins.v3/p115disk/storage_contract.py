"""MoviePilot V3 自定义存储合同。

只依赖本项目自己的存储语义和 ``P115StorageApi``。115 首版明确支持同盘 ``move``；
上传/复制在接口完成实机核准前不对宿主宣称可用。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from app import schemas


def _register_storage_selection(func):
    try:
        from app.core.event import eventmanager
        from app.schemas.types import ChainEventType
    except ImportError:
        return func
    return eventmanager.register(ChainEventType.StorageOperSelection)(func)


class P115StorageContractMixin:
    _disk_name = "115网盘助手"
    snapshot_check_folder_modtime = True

    def ensure_storage_registered(self) -> None:
        """通过 V3 稳定 StorageHelper 注册115自定义存储。"""
        try:
            from app.sdk.services import StorageHelper

            helper = StorageHelper()
            storages = helper.get_storagies() or []
            if not any(getattr(item, "type", None) == self._disk_name for item in storages):
                helper.add_storage(storage=self._disk_name, name=self._disk_name, conf={})
        except Exception as err:
            try:
                from app.sdk.logging import logger

                logger.warning("【115网盘助手】V3存储注册检查失败: %s", err)
            except Exception:
                pass

    def get_module(self) -> Dict[str, Any]:
        return {
            "list_files": self.list_files,
            "any_files": self.any_files,
            "download_file": self.download_file,
            "upload_file": self.upload_file,
            "delete_file": self.delete_file,
            "rename_file": self.rename_file,
            "get_file_item": self.get_file_item,
            "get_parent_item": self.get_parent_item,
            "snapshot_storage": self.snapshot_storage,
            "storage_usage": self.storage_usage,
            "support_transtype": self.support_transtype,
            "create_folder": self.create_folder,
            "exists": self.exists,
            "get_item": self.get_item,
            "get_folder": self.get_folder,
            "storage_manage": self.storage_manage,
        }

    @_register_storage_selection
    def storage_oper_selection(self, event: Any):
        if not getattr(self, "_enabled", False):
            return
        event_data = getattr(event, "event_data", None)
        if event_data and str(getattr(event_data, "storage", "") or "") == self._disk_name:
            event_data.storage_oper = getattr(self, "_storage_api", None)

    def _matches(self, storage: Any) -> bool:
        return str(storage or "") == self._disk_name

    def list_files(self, fileitem: schemas.FileItem, recursion: bool = False) -> Optional[List[schemas.FileItem]]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        if not api:
            return []
        result: List[schemas.FileItem] = []

        def walk(item: schemas.FileItem) -> None:
            children = api.list(item) or []
            if not recursion:
                result.extend(children)
                return
            for child in children:
                if child.type == "dir":
                    walk(child)
                else:
                    result.append(child)

        walk(fileitem)
        return result

    def any_files(self, fileitem: schemas.FileItem, extensions: list = None) -> Optional[bool]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        if not api:
            return False
        normalized_exts = {str(ext).lower() for ext in (extensions or [])}

        def has_any(item: schemas.FileItem) -> bool:
            for child in api.list(item) or []:
                if child.type == "file":
                    if not normalized_exts:
                        return True
                    ext = f".{str(child.extension or '').lower()}" if child.extension else ""
                    if ext in normalized_exts:
                        return True
                elif child.type == "dir" and has_any(child):
                    return True
            return False

        return has_any(fileitem)

    def create_folder(self, fileitem: schemas.FileItem, name: str) -> Optional[schemas.FileItem]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        return api.create_folder(fileitem, name) if api else None

    def download_file(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        return api.download(fileitem, path) if api else None

    def upload_file(self, fileitem: schemas.FileItem, path: Path, new_name: str = None):
        """首版不宣称跨存储上传可用；同盘整理通过 StorageOper.move 完成。"""
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        return None

    def delete_file(self, fileitem: schemas.FileItem) -> Optional[bool]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        return api.delete(fileitem) if api else False

    def rename_file(self, fileitem: schemas.FileItem, name: str) -> Optional[bool]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        return api.rename(fileitem, name) if api else False

    def exists(self, fileitem: schemas.FileItem) -> Optional[bool]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        return self.get_item(fileitem) is not None

    def get_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        return self.get_file_item(self._disk_name, Path(fileitem.path))

    def get_file_item(self, storage: str, path: Path) -> Optional[schemas.FileItem]:
        if not self._matches(storage):
            return None
        api = getattr(self, "_storage_api", None)
        return api.get_item(path) if api else None

    def get_parent_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        if not self._matches(getattr(fileitem, "storage", None)):
            return None
        api = getattr(self, "_storage_api", None)
        return api.get_parent(fileitem) if api else None

    def get_folder(self, storage: str, path: Path):
        if not self._matches(storage):
            return None
        api = getattr(self, "_storage_api", None)
        return api.get_folder(path) if api else None

    def snapshot_storage(
        self,
        storage: str,
        path: Path,
        last_snapshot_time: float = None,
        max_depth: int = 5,
        previous_snapshot: Optional[Dict[str, Dict]] = None,
    ) -> Optional[Dict[str, Dict]]:
        if not self._matches(storage):
            return None
        api = getattr(self, "_storage_api", None)
        if not api:
            return {}
        root = api.get_item(Path(path))
        if not root:
            return {}

        root_path = PurePosixPath(str(root.path or "/"))
        files_info: Dict[str, Dict] = {}
        for old_path, old_info in (previous_snapshot or {}).items():
            try:
                if PurePosixPath(str(old_path)).is_relative_to(root_path):
                    files_info[str(old_path)] = dict(old_info or {})
            except (TypeError, ValueError):
                continue

        def remove_deleted_children(directory: schemas.FileItem, children: list[schemas.FileItem]) -> None:
            directory_path = PurePosixPath(str(directory.path or "/"))
            visible = {PurePosixPath(str(child.path)) for child in children if child.path}
            for old_path in list(files_info):
                try:
                    relative = PurePosixPath(old_path).relative_to(directory_path)
                except ValueError:
                    continue
                if not relative.parts:
                    continue
                direct = directory_path / relative.parts[0]
                if direct not in visible:
                    files_info.pop(old_path, None)

        def visit(item: schemas.FileItem, depth: int = 0) -> None:
            if item.type == "dir":
                if depth >= max_depth:
                    return
                if (
                    depth > 0
                    and self.snapshot_check_folder_modtime
                    and last_snapshot_time
                    and item.modify_time
                    and item.modify_time <= last_snapshot_time
                ):
                    return
                children = list(api.list(item) or [])
                remove_deleted_children(item, children)
                for child in children:
                    visit(child, depth + 1)
                return
            files_info[str(item.path)] = {
                "size": int(item.size or 0),
                "modify_time": item.modify_time or 0,
                "fileid": item.fileid,
                "type": item.type or "file",
            }

        visit(root)
        return files_info

    def storage_usage(self, storage: str):
        if not self._matches(storage):
            return None
        api = getattr(self, "_storage_api", None)
        return api.usage() if api else None

    def support_transtype(self, storage: str) -> Optional[dict]:
        if not self._matches(storage):
            return None
        api = getattr(self, "_storage_api", None)
        return api.support_transtype() if api else {"move": "移动"}

    @staticmethod
    def _action_name(action: Any) -> str:
        return str(getattr(action, "value", action) or "").strip()

    @staticmethod
    def _dump(value: Any) -> Any:
        if value is None:
            return {}
        dump = getattr(value, "model_dump", None)
        return dump() if callable(dump) else value

    def storage_manage(self, storage: str, action: Any, **params: Any) -> Optional[Dict[str, Any]]:
        if not self._matches(storage):
            return None
        action_name = self._action_name(action)
        if action_name == "support_transtype":
            return {"success": True, "message": "", "data": {"transtype": self.support_transtype(storage) or {}}}
        if action_name == "usage":
            usage = self.storage_usage(storage)
            return {"success": True, "message": "", "data": self._dump(usage)}
        if action_name == "get_config":
            try:
                from app.sdk.services import StorageHelper

                conf = StorageHelper().get_storage(self._disk_name)
                return {"success": True, "message": "", "data": self._dump(conf)}
            except Exception as err:
                return {"success": False, "message": str(err), "data": {}}
        if action_name == "save_config":
            try:
                from app.sdk.services import StorageHelper

                StorageHelper().set_storage(self._disk_name, params.get("conf") or {})
                return {"success": True, "message": "", "data": {}}
            except Exception as err:
                return {"success": False, "message": str(err), "data": {}}
        if action_name == "reset_config":
            try:
                from app.sdk.services import StorageHelper

                StorageHelper().reset_storage(self._disk_name)
                return {"success": True, "message": "", "data": {}}
            except Exception as err:
                return {"success": False, "message": str(err), "data": {}}
        if action_name in {"check", "test_connection"}:
            try:
                api = getattr(self, "_storage_api", None)
                available = bool(api and api.get_item(Path("/")))
                return {
                    "success": available,
                    "message": "" if available else "115网盘未登录或根目录不可读",
                    "data": {"available": available},
                }
            except Exception as err:
                return {"success": False, "message": f"115网盘连接测试失败: {err}", "data": {"available": False}}
        if action_name == "generate_qrcode":
            return self.api_qr_start(params)
        if action_name == "check_login":
            return self.api_qr_poll(params)
        return {"success": False, "message": f"115网盘助手暂不支持存储管理动作：{action_name or 'unknown'}", "data": None}
