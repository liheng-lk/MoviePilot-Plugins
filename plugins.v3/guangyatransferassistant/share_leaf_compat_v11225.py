"""v1.12.25 光鸭分享叶子字段兼容。

实机现象：频道已精确命中分享，get_share_page_files_list 也返回 4/2 个叶子，
但 legacy probe 的 relative_path 全为空，最终被误报成“没有支持的视频/字幕扩展名；示例：-”。

当前公开光鸭脚本调用该接口时同时提交 shareId + accessToken；旧实现只提交 accessToken。
本层仅在 legacy probe 已有叶子、但所有叶子路径都为空时触发一次协议兼容重读：
- 补传 shareId（优先分享 ID 下划线前的基础 ID，同时兼容完整 ID）；
- 扩展常见文件名/路径/ID/扩展名字字段；
- 保留原来的递归、文件数上限、指纹与后续媒体身份/缺集硬门禁。

正常分享不会额外请求，也不改变 restore_share 提交语义。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple

from .legacy import (
    _extract_result_list,
    _is_subtitle,
    _is_video,
    _safe_relative_path,
    _share_identity,
)


_NAME_KEYS_V11225 = (
    "fileName", "filename", "file_name", "name", "displayName", "display_name",
    "resourceName", "resource_name", "resName", "objectName", "object_name",
    "originalName", "original_name", "fullName", "full_name", "title",
)
_PATH_KEYS_V11225 = (
    "relativePath", "relative_path", "filePath", "file_path", "fullPath", "full_path", "path",
)
_ID_KEYS_V11225 = (
    "fileId", "file_id", "id", "fid", "resId", "res_id", "resourceId", "resource_id", "objectId", "object_id",
)
_EXT_KEYS_V11225 = (
    "fileExt", "file_ext", "extension", "ext", "fileSuffix", "file_suffix", "suffix",
)
_SIZE_KEYS_V11225 = ("fileSize", "file_size", "size", "length", "contentLength", "content_length")
_DIGEST_KEYS_V11225 = ("sha1", "sha256", "md5", "hash", "etag")
_NESTED_KEYS_V11225 = ("fileInfo", "file_info", "resource", "resourceInfo", "resource_info", "item", "detail", "info")


def _first_v11225(mapping: Dict[str, Any], keys) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _candidate_maps_v11225(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = [raw]
    for key in _NESTED_KEYS_V11225:
        value = raw.get(key)
        if isinstance(value, dict):
            rows.append(value)
    data = raw.get("data")
    if isinstance(data, dict):
        rows.append(data)
        for key in _NESTED_KEYS_V11225:
            value = data.get(key)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _safe_int_v11225(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _leaf_item_v11225(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """兼容当前/历史光鸭分享节点；避免把 '.'/'/' 这类占位 name 当真实文件名。"""
    if not isinstance(raw, dict):
        return None
    maps = _candidate_maps_v11225(raw)

    file_id = None
    for row in maps:
        file_id = _first_v11225(row, _ID_KEYS_V11225)
        if file_id not in (None, ""):
            break
    if file_id in (None, ""):
        return None

    name = ""
    path_hint = ""
    ext = ""
    for row in maps:
        if not name:
            candidate = str(_first_v11225(row, _NAME_KEYS_V11225) or "").strip()
            if _safe_relative_path(candidate):
                name = candidate
        if not path_hint:
            candidate_path = str(_first_v11225(row, _PATH_KEYS_V11225) or "").strip()
            if _safe_relative_path(candidate_path):
                path_hint = candidate_path
        if not ext:
            ext = str(_first_v11225(row, _EXT_KEYS_V11225) or "").strip().lstrip(".")

    # 某些返回把 name 置为 '/' 或 '.'，真实名称只在 path/detail 内。
    if not _safe_relative_path(name) and path_hint:
        name = _safe_relative_path(path_hint).rsplit("/", 1)[-1]
    name = _safe_relative_path(name).rsplit("/", 1)[-1] if _safe_relative_path(name) else ""
    if not name:
        return None
    if ext and "." not in name.rsplit("/", 1)[-1]:
        name = f"{name}.{ext}"

    raw_type = None
    for row in maps:
        raw_type = _first_v11225(row, ("type", "resType", "res_type", "fileType", "file_type", "dirType", "dir_type", "kind"))
        if raw_type not in (None, ""):
            break
    is_dir = False
    for row in maps:
        flag = _first_v11225(row, ("isDir", "is_dir", "isFolder", "is_folder", "folder", "dir"))
        if flag not in (None, ""):
            if isinstance(flag, str):
                is_dir = flag.strip().lower() in {"1", "true", "yes", "dir", "folder"}
            else:
                is_dir = bool(flag)
            break
    if raw_type in (2, "2", "dir", "folder", "directory"):
        is_dir = True
    elif raw_type in (0, 1, "0", "1", "file"):
        is_dir = False

    size = 0
    digest = ""
    for row in maps:
        if not size:
            size = _safe_int_v11225(_first_v11225(row, _SIZE_KEYS_V11225))
        if not digest:
            digest = str(_first_v11225(row, _DIGEST_KEYS_V11225) or "").strip()

    return {
        "id": str(file_id),
        "name": name,
        "is_dir": is_dir,
        "size": size,
        "digest": digest,
        "path_hint_v11225": _safe_relative_path(path_hint),
    }


class GuangYaShareLeafCompatV11225Mixin:
    plugin_version = "1.12.25"
    build_id = "20260910-r72"

    @staticmethod
    def _probe_has_empty_leaf_paths_v11225(probe: Dict[str, Any]) -> bool:
        files = [row for row in (probe.get("files") or []) if isinstance(row, dict)]
        if not files:
            return False
        paths = [
            _safe_relative_path(row.get("relative_path") or row.get("name") or row.get("path") or "")
            for row in files
        ]
        return bool(paths) and not any(paths)

    def _inspect_share_with_share_id_v11225(self, share_url: str) -> Dict[str, Any]:
        identity = _share_identity(share_url)
        if not identity:
            return {"success": False, "message": "无效光鸭分享链接"}
        full_share_id, _ = identity.split("|", 1)
        list_share_ids = []
        base_share_id = full_share_id.split("_", 1)[0]
        for value in (base_share_id, full_share_id):
            if value and value not in list_share_ids:
                list_share_ids.append(value)

        client, _ = self._get_guangya_runtime()
        if not client:
            return {"success": False, "message": "光鸭云盘助手未运行或未登录"}
        token, error = self._share_access(client, share_url)
        if not token:
            return {"success": False, "message": error}

        last_error = ""
        for list_share_id in list_share_ids:
            stack: List[Tuple[str, str]] = [("", "")]
            root_ids: List[str] = []
            fingerprint_rows: List[str] = []
            legacy_fingerprint_rows: List[str] = []
            files: List[Dict[str, Any]] = []
            count = 0
            raw_key_samples: List[str] = []
            failed = False

            while stack and count < self._max_share_files:
                parent_id, parent_path = stack.pop()
                page = 1
                while count < self._max_share_files:
                    response = client._request(
                        method="POST",
                        url=f"{client.API_BASE_URL}/nd.bizuserres.s/v1/get_share_page_files_list",
                        data={
                            "shareId": list_share_id,
                            "accessToken": token,
                            "parentId": parent_id,
                            "page": page,
                            "pageSize": 100,
                            "orderBy": 0,
                            "sortType": 0,
                        },
                        need_auth=False,
                    )
                    if not self._is_success(response):
                        last_error = str(response.get("msg") or response.get("error") or "读取分享文件失败")
                        failed = True
                        break
                    raw_items = _extract_result_list(response)
                    for raw in raw_items[:4]:
                        if isinstance(raw, dict):
                            sample = ",".join(sorted(str(key) for key in raw.keys())[:24])
                            if sample and sample not in raw_key_samples:
                                raw_key_samples.append(sample)
                    for raw in raw_items:
                        item = _leaf_item_v11225(raw)
                        if not item:
                            continue
                        count += 1
                        rel_name = item.get("name") or ""
                        rel = _safe_relative_path("/".join(
                            value for value in (parent_path.strip("/"), str(rel_name).strip("/")) if value
                        ))
                        if not rel and item.get("path_hint_v11225"):
                            rel = _safe_relative_path(item.get("path_hint_v11225"))
                        fingerprint_rows.append(
                            f"{item['id']}|{rel}|{item['size']}|{int(item['is_dir'])}|{item.get('digest') or ''}"
                        )
                        legacy_fingerprint_rows.append(
                            f"{item['id']}|{item['name']}|{item['size']}|{int(item['is_dir'])}"
                        )
                        if parent_id == "":
                            root_ids.append(str(item.get("id") or ""))
                        if item["is_dir"]:
                            stack.append((item["id"], rel))
                        else:
                            files.append({**item, "relative_path": rel, "parent_path": parent_path})
                        if count >= self._max_share_files:
                            break
                    if len(raw_items) < 100:
                        break
                    page += 1
                if failed:
                    break

            if failed:
                continue
            valid_paths = [
                str(row.get("relative_path") or row.get("name") or "")
                for row in files
                if _safe_relative_path(row.get("relative_path") or row.get("name") or "")
            ]
            media_paths = [path for path in valid_paths if _is_video(path) or _is_subtitle(path)]
            if files and not valid_paths:
                last_error = "分享节点仍未返回可用文件名"
                continue

            fingerprint = hashlib.sha256("\n".join(sorted(fingerprint_rows)).encode("utf-8")).hexdigest()
            legacy_fingerprint = hashlib.sha256("\n".join(sorted(legacy_fingerprint_rows)).encode("utf-8")).hexdigest()
            result = {
                "success": True,
                "access_token": token,
                "root_ids": [value for value in root_ids if value],
                "fingerprint": fingerprint,
                "legacy_fingerprint": legacy_fingerprint,
                "file_count": count,
                "leaf_count": len(files),
                "files": files,
                "share_id_request_v11225": list_share_id,
                "raw_key_samples_v11225": raw_key_samples[:4],
            }
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【分享叶子兼容v1.12.25】share_id=%s 补传 shareId 后重读成功：节点=%s 叶子=%s 有效路径=%s 媒体=%s 字段=%s",
                full_share_id,
                count,
                len(files),
                len(valid_paths),
                len(media_paths),
                " | ".join(raw_key_samples[:2]) or "-",
            )
            self._inspect_cache[identity] = (time.time(), result)
            return dict(result)

        return {"success": False, "message": last_error or "补传 shareId 后仍无法读取分享文件"}

    def _inspect_share(self, share_url: str) -> Dict[str, Any]:
        result = dict(super()._inspect_share(share_url) or {})
        if not result.get("success") or not self._probe_has_empty_leaf_paths_v11225(result):
            return result

        identity = _share_identity(share_url)
        self._plugin_log(
            "WARNING",
            "【光鸭转存助手】【分享叶子兼容v1.12.25】share_id=%s legacy 已返回 %s 个叶子但路径全空；补传 shareId 并按新版字段重读",
            identity.split("|", 1)[0] if identity else "-",
            int(result.get("leaf_count") or len(result.get("files") or [])),
        )
        if identity:
            self._inspect_cache.pop(identity, None)
        recovered = dict(self._inspect_share_with_share_id_v11225(share_url) or {})
        if recovered.get("success"):
            return recovered
        # 不能把协议兼容失败伪装成“无视频”；显式返回读取失败，下一轮仍可重试。
        return {
            "success": False,
            "message": "分享叶子文件名读取异常：" + str(recovered.get("message") or "未知协议差异")[:360],
            "legacy_leaf_count": int(result.get("leaf_count") or len(result.get("files") or [])),
        }


__all__ = ["GuangYaShareLeafCompatV11225Mixin", "_leaf_item_v11225"]
