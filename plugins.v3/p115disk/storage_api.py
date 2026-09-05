"""115 MoviePilot 存储操作适配器。

本层只实现已经核准且首版整理必需的能力。MoviePilot 同盘整理通过 ``move`` 完成；
在 115 复制接口完成实机确认前，不声明 ``copy``，避免宿主选择一个实际上不可靠的整理方式。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

import requests

from app import schemas
from app.core.config import settings
from app.sdk.logging import logger

from .models import P115Item
from .p115_client import P115Gateway


class P115StorageApi:
    """把 115 文件系统能力映射为 MoviePilot StorageOper 语义。"""

    def __init__(self, gateway: P115Gateway, disk_name: str, page_size: int = 500):
        self.gateway = gateway
        self._disk_name = disk_name
        self._page_size = max(50, min(int(page_size or 500), 1150))
        self.transtype = {"move": "移动"}
        self._id_cache: Dict[str, int] = {"/": 0}
        self._item_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _normalize_path(path: Any) -> str:
        value = str(path or "/").replace("\\", "/")
        if not value.startswith("/"):
            value = "/" + value
        value = "/" + "/".join(part for part in value.split("/") if part)
        return value.rstrip("/") or "/"

    @classmethod
    def _parent_path(cls, path: Any) -> str:
        normalized = cls._normalize_path(path)
        if normalized == "/":
            return "/"
        return cls._normalize_path(str(PurePosixPath(normalized).parent))

    @staticmethod
    def _extract_raw_items(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Any] = [resp.get("data"), resp.get("list"), resp.get("files")]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if not isinstance(candidate, dict):
                continue
            for key in ("data", "list", "files"):
                value = candidate.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def _cache(self, item: schemas.FileItem) -> schemas.FileItem:
        path = self._normalize_path(item.path)
        try:
            file_id = int(str(item.fileid or 0))
        except (TypeError, ValueError):
            file_id = 0
        self._id_cache[path] = file_id
        model_dump = getattr(item, "model_dump", None)
        self._item_cache[path] = model_dump() if callable(model_dump) else dict(item)
        return item

    def _invalidate(self, path: Any) -> None:
        normalized = self._normalize_path(path)
        for cached_path in list(self._id_cache):
            if cached_path == "/":
                continue
            try:
                if PurePosixPath(cached_path).is_relative_to(PurePosixPath(normalized)):
                    self._id_cache.pop(cached_path, None)
                    self._item_cache.pop(cached_path, None)
            except (TypeError, ValueError):
                continue

    def _fileitem(self, raw: Dict[str, Any], parent_path: str) -> schemas.FileItem:
        item = P115Item.from_raw(raw)
        normalized_parent = self._normalize_path(parent_path)
        path = self._normalize_path(str(PurePosixPath(normalized_parent) / item.name))
        suffix = Path(item.name).suffix
        fileitem = schemas.FileItem(
            storage=self._disk_name,
            fileid=str(item.file_id),
            parent_fileid=str(item.parent_id),
            path=path + ("/" if item.is_dir else ""),
            type="dir" if item.is_dir else "file",
            name=item.name,
            basename=item.name if item.is_dir else Path(item.name).stem,
            extension=None if item.is_dir or not suffix else suffix[1:],
            pickcode=item.pickcode,
            size=None if item.is_dir else item.size,
            modify_time=item.modify_time or None,
        )
        return self._cache(fileitem)

    def root(self) -> schemas.FileItem:
        return self._cache(
            schemas.FileItem(
                storage=self._disk_name,
                fileid="0",
                parent_fileid="0",
                path="/",
                type="dir",
                name="/",
                basename="/",
            )
        )

    def _list_by_id(self, cid: int, parent_path: str) -> List[schemas.FileItem]:
        result: List[schemas.FileItem] = []
        offset = 0
        while True:
            resp = self.gateway.list_files(cid, offset=offset, limit=self._page_size)
            raw_items = self._extract_raw_items(resp)
            if not raw_items:
                break
            for raw in raw_items:
                try:
                    item = self._fileitem(raw, parent_path)
                    if item.name:
                        result.append(item)
                except Exception as err:
                    logger.debug("【115网盘助手】【存储】跳过异常条目: %s", err)
            if len(raw_items) < self._page_size:
                break
            offset += len(raw_items)
        return result

    def _path_to_id(self, path: Any) -> int:
        normalized = self._normalize_path(path)
        cached = self._id_cache.get(normalized)
        if cached is not None:
            return int(cached)
        current_id = 0
        current_path = "/"
        for part in PurePosixPath(normalized).parts[1:]:
            found: Optional[schemas.FileItem] = None
            for child in self._list_by_id(current_id, current_path):
                if child.name == part:
                    found = child
                    break
            if not found:
                raise FileNotFoundError(f"【115网盘助手】{normalized} 不存在")
            current_path = self._normalize_path(str(PurePosixPath(current_path) / part))
            try:
                current_id = int(str(found.fileid or 0))
            except (TypeError, ValueError) as err:
                raise FileNotFoundError(f"【115网盘助手】{normalized} 文件ID无效") from err
            self._id_cache[current_path] = current_id
        return current_id

    def list(self, fileitem: schemas.FileItem) -> List[schemas.FileItem]:
        if fileitem.type == "file":
            item = self.get_item(Path(fileitem.path))
            return [item] if item else []
        path = self._normalize_path(fileitem.path)
        try:
            cid = int(str(fileitem.fileid or "")) if str(fileitem.fileid or "") not in {"", "root"} else self._path_to_id(path)
        except (TypeError, ValueError, FileNotFoundError):
            cid = self._path_to_id(path)
        return self._list_by_id(cid, path)

    def get_item(self, path: Path) -> Optional[schemas.FileItem]:
        normalized = self._normalize_path(path)
        if normalized == "/":
            return self.root()
        cached = self._item_cache.get(normalized)
        if cached:
            try:
                return schemas.FileItem(**cached)
            except Exception:
                self._item_cache.pop(normalized, None)
        parent_path = self._parent_path(normalized)
        target_name = PurePosixPath(normalized).name
        try:
            parent_id = self._path_to_id(parent_path)
        except FileNotFoundError:
            return None
        for child in self._list_by_id(parent_id, parent_path):
            if child.name == target_name:
                return child
        return None

    def get_parent(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        return self.get_item(Path(self._parent_path(fileitem.path)))

    def create_folder(self, fileitem: schemas.FileItem, name: str) -> Optional[schemas.FileItem]:
        parent_path = self._normalize_path(fileitem.path)
        if not str(name or "").strip():
            return None
        try:
            parent_id = int(str(fileitem.fileid or "")) if str(fileitem.fileid or "") not in {"", "root"} else self._path_to_id(parent_path)
        except (TypeError, ValueError, FileNotFoundError):
            parent_id = self._path_to_id(parent_path)
        resp = self.gateway.mkdir(str(name).strip(), parent_id)
        if not self.gateway._ok(resp):
            return None
        self._invalidate(parent_path)
        for child in self._list_by_id(parent_id, parent_path):
            if child.type == "dir" and child.name == str(name).strip():
                return child
        return None

    def get_folder(self, path: Path) -> Optional[schemas.FileItem]:
        normalized = self._normalize_path(path)
        item = self.get_item(Path(normalized))
        if item and item.type == "dir":
            return item
        current = self.root()
        for part in PurePosixPath(normalized).parts[1:]:
            next_item = None
            for child in self.list(current):
                if child.type == "dir" and child.name == part:
                    next_item = child
                    break
            if not next_item:
                next_item = self.create_folder(current, part)
            if not next_item:
                return None
            current = next_item
        return current

    def rename(self, fileitem: schemas.FileItem, name: str) -> bool:
        try:
            resp = self.gateway.rename(int(str(fileitem.fileid)), str(name).strip())
            if not self.gateway._ok(resp):
                return False
            old_path = self._normalize_path(fileitem.path)
            parent = self._parent_path(old_path)
            self._invalidate(old_path)
            expected = self._normalize_path(str(PurePosixPath(parent) / str(name).strip()))
            visible = self.get_item(Path(expected))
            return bool(visible and visible.name == str(name).strip())
        except Exception as err:
            logger.warning("【115网盘助手】【存储】重命名失败: %s", err)
            return False

    def delete(self, fileitem: schemas.FileItem) -> bool:
        try:
            resp = self.gateway.delete([int(str(fileitem.fileid))])
            if not self.gateway._ok(resp):
                return False
            old_path = self._normalize_path(fileitem.path)
            self._invalidate(old_path)
            return self.get_item(Path(old_path)) is None
        except Exception as err:
            logger.warning("【115网盘助手】【存储】删除失败: %s", err)
            return False

    def move(self, fileitem: schemas.FileItem, path: Path, new_name: str = "") -> bool:
        source_path = self._normalize_path(fileitem.path)
        target_parent = self._normalize_path(path)
        current_parent = self._parent_path(source_path)
        current_name = fileitem.name or PurePosixPath(source_path).name
        target_name = str(new_name or current_name)
        if target_parent == current_parent:
            return True if target_name == current_name else self.rename(fileitem, target_name)
        try:
            target_item = self.get_folder(Path(target_parent))
            if not target_item:
                return False
            resp = self.gateway.move([int(str(fileitem.fileid))], int(str(target_item.fileid or 0)))
            if not self.gateway._ok(resp):
                return False
            self._invalidate(source_path)
            moved_path = self._normalize_path(str(PurePosixPath(target_parent) / current_name))
            moved_item = self.get_item(Path(moved_path))
            if not moved_item:
                return False
            if target_name != current_name:
                if not self.rename(moved_item, target_name):
                    return False
                moved_path = self._normalize_path(str(PurePosixPath(target_parent) / target_name))
            final_item = self.get_item(Path(moved_path))
            return bool(final_item and final_item.name == target_name)
        except Exception as err:
            logger.warning("【115网盘助手】【存储】移动失败: %s", err)
            return False

    def download(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
        if fileitem.type != "file" or not fileitem.pickcode:
            return None
        try:
            raw = self.gateway.download_url(str(fileitem.pickcode))
            url = ""
            if isinstance(raw, str):
                url = raw
            elif isinstance(raw, dict):
                data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
                candidate = data.get("url") or data.get("download_url") or data.get("downloadUrl")
                if isinstance(candidate, dict):
                    url = str(candidate.get("url") or "")
                else:
                    url = str(candidate or "")
            else:
                url = str(getattr(raw, "url", "") or raw or "")
            if not url:
                return None
            target_dir = Path(path or settings.TEMP_PATH)
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / fileitem.name
            with requests.get(url, stream=True, timeout=300) as response:
                response.raise_for_status()
                with target_file.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                        if chunk:
                            output.write(chunk)
            return target_file
        except Exception as err:
            logger.warning("【115网盘助手】【存储】下载失败: %s", err)
            return None

    def support_transtype(self) -> dict:
        return dict(self.transtype)

    def is_support_transtype(self, transtype: str) -> bool:
        return str(transtype or "") in self.transtype

    def usage(self):
        return None

    def link(self, _fileitem: schemas.FileItem, _target_file: Path) -> bool:
        return False

    def softlink(self, _fileitem: schemas.FileItem, _target_file: Path) -> bool:
        return False
