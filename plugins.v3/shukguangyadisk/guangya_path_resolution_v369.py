"""v3.6.9：光鸭路径解析分页、实例缓存隔离与严格目录读取。

长期运行中自动整理高度依赖 ``get_item(path) -> list(dir)``。旧实现存在三个会互相放大的问题：

1. ``_path_to_id`` 每一级只读取 get_file_list 第 0 页；父目录超过 page_size（默认 100）时，
   第二页以后的真实目录会被误判为“不存在”。
2. ``_id_cache`` / ``_item_cache`` 定义为类属性，热重载、新账号或新 API 实例会继承旧实例的
   path->fileId 缓存，可能把已经变化的目录继续解析到旧 fileId。
3. legacy ``list`` 遇到上游 API 失败时直接 break 并返回当前结果，调用方无法区分“真实空目录”
   与“网络/API 失败后的空列表”。自动整理因此可能把故障误判为资源已经搬空。

本模块不改变 MoviePilot 业务规则，只收紧光鸭存储查询语义：
- 路径逐级完整分页；
- 每个 GuangYaApi 实例拥有独立缓存；
- ``list_strict`` 只有上游明确成功时才返回列表，失败必须抛异常；
- ``get_item`` 复用逐级解析时已经建立的 item cache，避免再列一次父目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.sdk.logging import logger

from .guangya_api_v112 import GuangYaApi


_PATCH_FLAG = "_guangya_path_resolution_v369"


def _response_success(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    return response.get("code", -1) == 0 or response.get("msg") == "success"


def _response_error(response: Any) -> str:
    if not isinstance(response, dict):
        return repr(response)
    return str(
        response.get("error")
        or response.get("msg")
        or response.get("message")
        or f"code={response.get('code')}"
    )


def _page_has_more(data: Dict[str, Any], page_size: int, page_items: int, accumulated: int) -> bool:
    try:
        total = int(data.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    if page_items <= 0:
        return False
    if total > 0:
        return accumulated < total
    return page_items >= page_size


def install_path_resolution_v369() -> None:
    """幂等安装到当前 V3 GuangYaApi；不修改 V2。"""
    if getattr(GuangYaApi, _PATCH_FLAG, False):
        return

    previous_init = GuangYaApi.__init__
    previous_get_item = GuangYaApi.get_item

    def __init__(self: GuangYaApi, *args: Any, **kwargs: Any) -> None:
        previous_init(self, *args, **kwargs)
        # legacy 把缓存定义成类属性；必须在实例初始化时遮蔽，禁止热重载/多账号共享旧 fileId。
        self._id_cache = {}
        self._item_cache = {}

    def _path_to_id(self: GuangYaApi, path: str) -> str:
        normalized_path = self._normalize_path(path)
        if normalized_path == "/":
            return ""
        cached = str(self._id_cache.get(normalized_path) or "")
        if cached:
            return cached

        current_id = ""
        current_path = "/"
        for part in Path(normalized_path).parts[1:]:
            page = 0
            found: Optional[Dict[str, Any]] = None
            accumulated = 0
            while True:
                response = self.client.get_file_list(
                    parent_id=current_id,
                    page_size=self._page_size,
                    order_by=self._order_by,
                    sort_type=self._sort_type,
                    file_types=[],
                    page=page,
                )
                if not _response_success(response):
                    raise RuntimeError(
                        f"【光鸭云盘助手】解析路径 {normalized_path} 时读取目录失败: "
                        f"parent={current_path} page={page} error={_response_error(response)}"
                    )

                data = dict(response.get("data") or {})
                items = list(data.get("list") or [])
                accumulated += len(items)
                for item in items:
                    if str(item.get("fileName") or "") == part:
                        found = dict(item)
                        break
                if found is not None:
                    break
                if not _page_has_more(data, self._page_size, len(items), accumulated):
                    break
                page += 1

            if found is None:
                raise FileNotFoundError(f"【光鸭云盘助手】{normalized_path} 不存在")

            current_id = str(found.get("fileId") or "")
            current_path = (
                f"{current_path.rstrip('/')}/{part}" if current_path != "/" else f"/{part}"
            )
            self._cache_path_id(current_path, current_id)
            parent_path = str(Path(current_path).parent).replace("\\", "/") or "/"
            self._build_file_item_from_api(parent_path, found)

        return current_id

    def list_strict(self: GuangYaApi, fileitem: Any) -> List[Any]:
        """完整分页目录读取；上游失败抛异常，绝不伪装成成功空目录。"""
        if str(getattr(fileitem, "type", "") or "") == "file":
            item = self.detail(fileitem)
            return [item] if item else []

        normalized_dir_path = self._normalize_path(getattr(fileitem, "path", "/"))
        file_id = self._normalize_fileid(getattr(fileitem, "fileid", ""), normalized_dir_path)
        if normalized_dir_path != "/" and not file_id:
            file_id = self._path_to_id(normalized_dir_path)

        results: List[Any] = []
        page = 0
        while True:
            response = self.client.get_file_list(
                parent_id=file_id,
                page_size=self._page_size,
                order_by=self._order_by,
                sort_type=self._sort_type,
                file_types=[],
                page=page,
            )
            if not _response_success(response):
                raise RuntimeError(
                    f"【光鸭云盘助手】读取目录失败: path={normalized_dir_path} page={page} "
                    f"error={_response_error(response)}"
                )
            data = dict(response.get("data") or {})
            item_list = list(data.get("list") or [])
            for item in item_list:
                results.append(self._build_file_item_from_api(normalized_dir_path, item))
            if not _page_has_more(data, self._page_size, len(item_list), len(results)):
                break
            page += 1
        return results

    def get_item(self: GuangYaApi, path: Path):
        normalized = self._normalize_path(str(path))
        if normalized == "/":
            return previous_get_item(self, path)

        cached_item = self._restore_cached_item(normalized)
        if cached_item:
            return cached_item
        try:
            file_id = self._path_to_id(normalized)
        except FileNotFoundError:
            return None

        # 分页 _path_to_id 已把最终 segment 构造成 FileItem 并写入 cache，避免旧实现再次
        # 枚举父目录；只有异常兼容场景才退回旧父目录确认逻辑。
        resolved = self._restore_cached_item(normalized)
        if resolved and str(getattr(resolved, "fileid", "") or "") == str(file_id or ""):
            return resolved
        return previous_get_item(self, path)

    def refresh_item(self: GuangYaApi, path: Path):
        """丢弃指定路径陈旧缓存后重新从远端解析。"""
        normalized = self._normalize_path(str(path))
        self._invalidate_path_cache(normalized)
        return get_item(self, Path(normalized))

    GuangYaApi.__init__ = __init__
    GuangYaApi._path_to_id = _path_to_id
    GuangYaApi.list_strict = list_strict
    GuangYaApi.get_item = get_item
    GuangYaApi.refresh_item = refresh_item
    setattr(GuangYaApi, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.9】路径查询增强已启用：完整分页、实例缓存隔离、严格目录失败语义"
    )


__all__ = ["install_path_resolution_v369"]
