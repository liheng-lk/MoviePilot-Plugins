"""迅雷分享 -> 光鸭秒传 JSON 构建器。

复刻光鸭秒传脚本 1.1.3 的 JSON 中间格式。
不负责迅雷下载，不调用迅雷客户端，仅负责生成可导入光鸭的模板。
"""

from typing import Any, Dict, Iterable, List, Optional


class XunleiJsonBuilder:
    """Build GuangYa compatible Xunlei rapid-transfer JSON."""

    SCRIPT_VERSION = "1.1.3"
    SCRIPT_AUTHOR = "sumuve"

    def __init__(
        self,
        share_id: str = "",
        pass_code_token: str = "",
    ):
        self.share_id = str(share_id or "")
        self.pass_code_token = str(pass_code_token or "")

    @staticmethod
    def _normalize_file(item: Dict[str, Any], share_id: str, pass_code_token: str) -> Dict[str, Any]:
        row = {
            "size": str(item.get("size") or "0"),
            "path": str(item.get("path") or item.get("name") or ""),
            "gcid": str(item.get("gcid") or ""),
            "md5": str(item.get("md5") or ""),
            "fileId": str(item.get("fileId") or ""),
            "cid": str(item.get("cid") or ""),
            "parentId": str(item.get("parentId") or ""),
            "downloadUrl": str(item.get("downloadUrl") or ""),
            "sourceXunlei": True,
            "shareId": str(item.get("shareId") or share_id or ""),
            "passCodeToken": str(item.get("passCodeToken") or pass_code_token or ""),
        }

        # 兼容新版脚本字段
        for key in ("etag", "wholeCid", "tripleCid"):
            if item.get(key) is not None:
                row[key] = str(item.get(key) or "")

        return row

    def build(
        self,
        files: Iterable[Dict[str, Any]],
        share_id: Optional[str] = None,
        pass_code_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        share_id = str(share_id or self.share_id or "")
        pass_code_token = str(pass_code_token or self.pass_code_token or "")

        normalized: List[Dict[str, Any]] = [
            self._normalize_file(f, share_id, pass_code_token)
            for f in files
            if isinstance(f, dict)
        ]

        total_size = sum(
            int(f.get("size") or 0)
            for f in normalized
            if str(f.get("size") or "0").isdigit()
        )

        return {
            "scriptVersion": self.SCRIPT_VERSION,
            "scriptAuthor": self.SCRIPT_AUTHOR,
            "totalFilesCount": len(normalized),
            "totalSize": total_size,
            "files": normalized,
            "sourceTag": "xunlei",
            "shareId": share_id,
            "passCodeToken": pass_code_token,
        }

    @classmethod
    def from_resource(cls, resource: Dict[str, Any]) -> Dict[str, Any]:
        """方便 resource_planner 直接调用。"""
        builder = cls(
            share_id=resource.get("shareId") or resource.get("share_id"),
            pass_code_token=resource.get("passCodeToken") or resource.get("pass_code_token"),
        )
        return builder.build(resource.get("files") or [])
