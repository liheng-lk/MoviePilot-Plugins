"""115 转存执行 Provider。

该 Provider 与 ``p115disk`` 插件保持独立，避免转存助手依赖另一个插件实例的生命周期。
两者共同依赖 ``p115client``，但分别维护自己的宿主职责。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from p115client import P115Client


class P115TransferProvider:
    def __init__(self, cookies: str = "", cookies_file: str = ""):
        source: Any = Path(cookies_file).expanduser() if cookies_file else (cookies or None)
        self.client = P115Client(source)

    @staticmethod
    def is_ok(resp: Any) -> bool:
        if isinstance(resp, dict):
            if "state" in resp:
                return bool(resp.get("state"))
            if "success" in resp:
                return bool(resp.get("success"))
            if resp.get("error"):
                return False
        return resp is not None

    def share_receive(
        self,
        *,
        share_code: str,
        receive_code: str,
        file_ids: Iterable[int],
        target_cid: int,
    ) -> Dict[str, Any]:
        ids = [str(int(file_id)) for file_id in file_ids]
        if not ids:
            raise ValueError("115 分享转存没有可提交文件")
        method = getattr(self.client, "share_receive", None)
        if not callable(method):
            raise RuntimeError("p115client 缺少 share_receive")
        payload = {
            "share_code": share_code,
            "receive_code": receive_code,
            "file_id": ",".join(ids),
            "cid": int(target_cid),
        }
        resp = method(payload)
        return resp if isinstance(resp, dict) else {"state": bool(resp)}

    def offline_add_url(self, *, uri: str, target_cid: int) -> Dict[str, Any]:
        method = getattr(self.client, "clouddownload_task_add_url", None)
        if not callable(method):
            raise RuntimeError("p115client 缺少 clouddownload_task_add_url")
        resp = method({"url": uri, "wp_path_id": int(target_cid)})
        return resp if isinstance(resp, dict) else {"state": bool(resp)}

    def offline_add_bt(
        self,
        *,
        info_hash: str,
        target_cid: int,
        wanted: Optional[Iterable[int]] = None,
    ) -> Dict[str, Any]:
        method = getattr(self.client, "clouddownload_task_add_bt", None)
        if not callable(method):
            raise RuntimeError("p115client 缺少 clouddownload_task_add_bt")
        payload: Dict[str, Any] = {
            "info_hash": info_hash,
            "wp_path_id": int(target_cid),
        }
        if wanted is not None:
            wanted_values = [str(int(index)) for index in wanted]
            if wanted_values:
                payload["wanted"] = ",".join(wanted_values)
        resp = method(payload)
        return resp if isinstance(resp, dict) else {"state": bool(resp)}

    def list_offline_tasks(self) -> Dict[str, Any]:
        method = getattr(self.client, "clouddownload_task_list", None)
        if callable(method):
            resp = method({})
            return resp if isinstance(resp, dict) else {}
        method = getattr(self.client, "clouddownload_task", None)
        if callable(method):
            resp = method({})
            return resp if isinstance(resp, dict) else {}
        return {}
