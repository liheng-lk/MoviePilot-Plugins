"""115 客户端薄封装。

只依赖 MIT 许可的 ``p115client``。本层不把第三方 MoviePilot 插件代码复制进来，
而是把 115 能力收敛成当前项目需要的稳定边界。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from p115client import P115Client


@dataclass(slots=True)
class P115ClientConfig:
    cookies: str = ""
    cookies_file: str = ""
    app: str = "qandroid"


class P115Gateway:
    """对 ``P115Client`` 做最小稳定包装，并集中处理接口漂移。"""

    def __init__(self, config: P115ClientConfig):
        self.config = config
        if config.cookies_file:
            cookies: Any = Path(config.cookies_file).expanduser()
        elif config.cookies:
            cookies = config.cookies
        else:
            raise RuntimeError("115 尚未登录，请先扫码登录或填写 Cookie")
        self.client = P115Client(cookies)

    @staticmethod
    def _ok(resp: Any) -> bool:
        if resp is None:
            return False
        if isinstance(resp, bool):
            return resp
        if not isinstance(resp, dict):
            return True
        if "state" in resp:
            return bool(resp.get("state"))
        if "success" in resp:
            return bool(resp.get("success"))
        code = resp.get("code")
        if code is not None:
            try:
                return int(code) in (0, 200)
            except (TypeError, ValueError):
                pass
        return not bool(resp.get("error"))

    def user_info(self) -> Dict[str, Any]:
        for name in ("user_base_info", "user_info", "user_info_app", "user_my"):
            method = getattr(self.client, name, None)
            if callable(method):
                resp = method()
                if isinstance(resp, dict):
                    return resp
        return {}

    def list_files(self, cid: int = 0, *, offset: int = 0, limit: int = 1000) -> Dict[str, Any]:
        payload = {
            "cid": int(cid or 0),
            "offset": max(0, int(offset or 0)),
            "limit": max(1, min(int(limit or 1000), 1150)),
            "show_dir": 1,
        }
        for name in ("fs_files", "fs_files_app"):
            method = getattr(self.client, name, None)
            if callable(method):
                resp = method(payload)
                if isinstance(resp, dict):
                    return resp
        raise RuntimeError("当前 p115client 未暴露可用的文件列表接口")

    def mkdir(self, name: str, pid: int = 0) -> Dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise ValueError("目录名称不能为空")
        method = getattr(self.client, "fs_mkdir", None)
        if callable(method):
            resp = method({"cname": name, "pid": int(pid or 0)})
            if isinstance(resp, dict):
                return resp
        method = getattr(self.client, "fs_mkdir_app", None)
        if callable(method):
            resp = method({"cname": name, "pid": int(pid or 0)})
            if isinstance(resp, dict):
                return resp
        raise RuntimeError("当前 p115client 未暴露可用的创建目录接口")

    def rename(self, file_id: int, name: str) -> Dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise ValueError("新名称不能为空")
        method = getattr(self.client, "fs_rename", None)
        if callable(method):
            resp = method((int(file_id), name))
            if isinstance(resp, dict):
                return resp
        method = getattr(self.client, "fs_rename_app", None)
        if callable(method):
            resp = method({"fid": int(file_id), "file_name": name})
            if isinstance(resp, dict):
                return resp
        raise RuntimeError("当前 p115client 未暴露可用的重命名接口")

    def move(self, file_ids: Iterable[int], pid: int) -> Dict[str, Any]:
        ids = [int(fid) for fid in file_ids]
        if not ids:
            raise ValueError("没有可移动文件")
        method = getattr(self.client, "fs_move", None)
        if callable(method):
            resp = method(ids if len(ids) > 1 else ids[0], pid=int(pid))
            if isinstance(resp, dict):
                return resp
        method = getattr(self.client, "fs_move_app", None)
        if callable(method):
            resp = method({"fid": ids, "pid": int(pid)})
            if isinstance(resp, dict):
                return resp
        raise RuntimeError("当前 p115client 未暴露可用的移动接口")

    def delete(self, file_ids: Iterable[int]) -> Dict[str, Any]:
        ids = [int(fid) for fid in file_ids]
        if not ids:
            raise ValueError("没有可删除文件")
        method = getattr(self.client, "fs_delete", None)
        if callable(method):
            resp = method(ids if len(ids) > 1 else ids[0])
            if isinstance(resp, dict):
                return resp
        method = getattr(self.client, "fs_delete_app", None)
        if callable(method):
            resp = method({"fid": ids})
            if isinstance(resp, dict):
                return resp
        raise RuntimeError("当前 p115client 未暴露可用的删除接口")

    def download_url(self, pickcode: str) -> Any:
        for method_name in ("download_url", "download_url_app"):
            method = getattr(self.client, method_name, None)
            if callable(method):
                return method(pickcode)
        raise RuntimeError("当前 p115client 未暴露可用的下载地址接口")

    def share_list(self, share_code: str, receive_code: str = "", cid: int = 0, *, offset: int = 0, limit: int = 1000) -> Dict[str, Any]:
        payload = {
            "share_code": share_code,
            "receive_code": receive_code,
            "cid": int(cid or 0),
            "offset": max(0, int(offset or 0)),
            "limit": max(1, int(limit or 1000)),
        }
        for method_name in ("share_snap", "share_snap_app", "share_snap_cookie"):
            method = getattr(self.client, method_name, None)
            if callable(method):
                resp = method(payload)
                if isinstance(resp, dict):
                    return resp
        raise RuntimeError("当前 p115client 未暴露可用的分享列表接口")

    def share_receive(self, share_code: str, receive_code: str, file_ids: Iterable[int], cid: int) -> Dict[str, Any]:
        ids = [str(int(fid)) for fid in file_ids]
        if not ids:
            raise ValueError("115 分享转存没有可提交文件")
        payload = {
            "share_code": share_code,
            "receive_code": receive_code,
            "file_id": ",".join(ids),
            "cid": int(cid),
            "is_check": 0,
        }
        method = getattr(self.client, "share_receive", None)
        if not callable(method):
            raise RuntimeError("当前 p115client 未暴露 share_receive")
        resp = method(payload)
        return resp if isinstance(resp, dict) else {"state": bool(resp)}

    def offline_add_url(self, url: str, cid: int) -> Dict[str, Any]:
        payload = {"url": url, "wp_path_id": int(cid)}
        method = getattr(self.client, "clouddownload_task_add_url", None)
        if not callable(method):
            raise RuntimeError("当前 p115client 未暴露 clouddownload_task_add_url")
        resp = method(payload)
        return resp if isinstance(resp, dict) else {"state": bool(resp)}

    def offline_add_bt(self, info_hash: str, cid: int, wanted: Optional[Iterable[int]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"info_hash": info_hash, "wp_path_id": int(cid)}
        if wanted is not None:
            wanted_values = [str(int(index)) for index in wanted]
            if wanted_values:
                payload["wanted"] = ",".join(wanted_values)
        method = getattr(self.client, "clouddownload_task_add_bt", None)
        if not callable(method):
            raise RuntimeError("当前 p115client 未暴露 clouddownload_task_add_bt")
        resp = method(payload)
        return resp if isinstance(resp, dict) else {"state": bool(resp)}

    def offline_tasks(self, *, page: int = 1, page_size: int = 30) -> Dict[str, Any]:
        method = getattr(self.client, "clouddownload_task_list", None)
        if not callable(method):
            return {}
        resp = method({"page": max(1, int(page)), "page_size": max(1, int(page_size))})
        return resp if isinstance(resp, dict) else {}
