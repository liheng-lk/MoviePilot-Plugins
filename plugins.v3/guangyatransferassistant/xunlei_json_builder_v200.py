"""迅雷分享 -> 光鸭 scriptVersion 1.1.3 JSON 构建器。

只负责生成通用模板，不负责迅雷下载，也不调用迅雷接口。
上层 xunlei flash 流程决定是否使用 JSON 导入。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


SCRIPT_VERSION = "1.1.3"
SCRIPT_AUTHOR = "sumuve"


class XunleiJsonBuilder:
    """构建光鸭可识别的迅雷分享 JSON 模板。"""

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def normalize_file(
        cls,
        item: Dict[str, Any],
        *,
        share_id: str = "",
        pass_code_token: str = "",
    ) -> Dict[str, Any]:
        return {
            "size": str(item.get("size") or item.get("fileSize") or ""),
            "path": str(item.get("path") or item.get("name") or ""),
            "gcid": str(item.get("gcid") or item.get("GCID") or ""),
            "md5": str(item.get("md5") or ""),
            "fileId": str(item.get("fileId") or item.get("file_id") or ""),
            "cid": str(item.get("cid") or ""),
            "parentId": str(item.get("parentId") or item.get("parent_id") or ""),
            "downloadUrl": str(item.get("downloadUrl") or item.get("download_url") or ""),
            "etag": str(item.get("etag") or ""),
            "wholeCid": str(item.get("wholeCid") or item.get("whole_cid") or ""),
            "tripleCid": str(item.get("tripleCid") or item.get("triple_cid") or ""),
            "sourceXunlei": True,
            "shareId": str(share_id or item.get("shareId") or ""),
            "passCodeToken": str(pass_code_token or item.get("passCodeToken") or ""),
        }

    @classmethod
    def build(
        cls,
        files: Iterable[Dict[str, Any]],
        *,
        share_id: str = "",
        pass_code_token: str = "",
    ) -> Dict[str, Any]:
        normalized: List[Dict[str, Any]] = [
            cls.normalize_file(
                item,
                share_id=share_id,
                pass_code_token=pass_code_token,
            )
            for item in (files or [])
            if isinstance(item, dict)
        ]

        return {
            "scriptVersion": SCRIPT_VERSION,
            "scriptAuthor": SCRIPT_AUTHOR,
            "totalFilesCount": len(normalized),
            "totalSize": sum(cls._int(item.get("size")) for item in normalized),
            "files": normalized,
            "sourceTag": "xunlei",
            "shareId": str(share_id or ""),
            "passCodeToken": str(pass_code_token or ""),
        }
