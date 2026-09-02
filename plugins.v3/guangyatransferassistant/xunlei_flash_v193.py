"""v1.9.3：观影迅雷分享 -> 光鸭秒传最高优先级。

只复用迅雷分享元数据和光鸭秒传接口，不把迅雷文件下载到 MoviePilot 本地：
观影 -> 迅雷分享 -> share/pass_code_token -> GCID/CID -> 光鸭 get_res_center_token /
check_can_flash_upload -> get_info_by_task_id。秒传不命中时才回退光鸭分享、Magnet、ED2K。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .content_resilience_v1105 import is_auxiliary_media_v1105
from .legacy import _is_subtitle, _is_video, _normalize_media_text
from .provider_sources_v192 import _GyingSearchParser, _proxy_dict


XUNLEI_API_BASE = "https://api-pan.xunlei.com"
XUNLEI_CAPTCHA_INIT = "https://xluser-ssl.xunlei.com/v1/shield/captcha/init"
XUNLEI_DEFAULT_CLIENT_ID = "Xqp0kJBXWhwaTpB6"
_XUNLEI_URL_RE = re.compile(r"https?://pan\.xunlei\.com/s/[^\s\"'<>，。；;]+", re.I)
_PASSCODE_RE = re.compile(r"(?:提取码|访问码|密码|口令|pass\s*code|passcode|pwd)\s*[:：=]?\s*([A-Za-z0-9]{1,16})", re.I)
_HEX40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _pick_download_url(value: Any) -> str:
    """从迅雷 file_info/share/detail 的多种 links 结构里取真实下载链接。"""
    preferred: List[str] = []
    fallback: List[str] = []

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for child_key, child in node.items():
                walk(child, str(child_key or ""))
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child, key)
            return
        if not isinstance(node, str):
            return
        text = node.strip().strip("`\"'")
        if not text.lower().startswith(("http://", "https://")):
            return
        # 迅雷详情里会混入封面/缩略图 CDN。稳定脚本明确拒绝把这些 URL
        # 当成文件下载地址，否则 Range 计算得到的是图片 CID，秒传必败。
        parsed = urlparse(text)
        host = str(parsed.hostname or "").lower()
        path = str(parsed.path or "").lower()
        if (
            any(token in host for token in ("88cdn", "xlpan", "thumbnail", "image"))
            and any(token in path for token in ("thumb", "image", "cover", "poster", "backstage"))
        ) or any(token in text.lower() for token in ("backstage-img", "thumbnail_size=")):
            return
        lowered = key.lower()
        if any(token in lowered for token in ("web_content_link", "download", "octet", "url")):
            preferred.append(text)
        else:
            fallback.append(text)

    walk(value)
    return (preferred or fallback or [""])[0]


def parse_xunlei_share(value: str, *, label: str = "") -> List[Dict[str, str]]:
    """从观影返回文本中提取迅雷分享 ID、分享 URL 与可能的提取码。"""
    text = html.unescape(str(value or ""))
    rows: List[Dict[str, str]] = []
    for match in _XUNLEI_URL_RE.finditer(text):
        raw_url = match.group(0).rstrip(").]】）}")
        parsed = urlparse(raw_url)
        share_match = re.search(r"^/s/([^/?#]+)", parsed.path or "", re.I)
        if not share_match:
            continue
        share_id = share_match.group(1).strip()
        query = parse_qs(parsed.query or "")
        passcode = ""
        for key in ("pwd", "passcode", "pass_code", "code"):
            values = query.get(key) or []
            if values and str(values[0] or "").strip():
                passcode = str(values[0]).strip()
                break
        if not passcode:
            around = f"{label} {text[max(0, match.start()-80):min(len(text), match.end()+100)]}"
            pass_match = _PASSCODE_RE.search(around)
            if pass_match:
                passcode = pass_match.group(1).strip()
        rows.append({
            "type": "xunlei",
            "uri": raw_url,
            "identity": share_id,
            "share_id": share_id,
            "passcode": passcode,
            "name": str(label or "").strip(),
            "provider": "viewing",
        })
    by_id: Dict[str, Dict[str, str]] = {}
    for row in rows:
        old = by_id.get(row["share_id"])
        if not old or (not old.get("passcode") and row.get("passcode")):
            by_id[row["share_id"]] = row
    return list(by_id.values())


class GuangYaXunleiFlashMixin:
    """在 ResourcePlanner 之前尝试观影迅雷分享秒传。"""

    _xunlei_flash_enabled = True
    _xunlei_client_id = XUNLEI_DEFAULT_CLIENT_ID
    _xunlei_device_id = ""
    _xunlei_captcha_token = ""
    _xunlei_captcha_init_json = ""
    _xunlei_flash_max_files = 80
    _xunlei_runtime_captcha_token = ""
    _xunlei_runtime_reservations: Dict[int, Dict[str, Any]] = {}

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        self._xunlei_flash_enabled = bool(config.get("xunlei_flash_enabled", True))
        self._xunlei_client_id = str(config.get("xunlei_client_id") or XUNLEI_DEFAULT_CLIENT_ID).strip()
        self._xunlei_device_id = str(config.get("xunlei_device_id") or "").strip()
        self._xunlei_captcha_token = str(config.get("xunlei_captcha_token") or "").strip()
        self._xunlei_captcha_init_json = str(config.get("xunlei_captcha_init_json") or "").strip()
        self._xunlei_flash_max_files = max(1, min(_safe_int(config.get("xunlei_flash_max_files"), 80), 500))
        self._xunlei_runtime_captcha_token = self._xunlei_captcha_token
        self._xunlei_runtime_reservations = {}
        super().init_plugin(config)

    def _search_viewing_xunlei(self, keyword: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self._xunlei_flash_enabled:
            return [], {"provider": "viewing_xunlei", "enabled": False, "success": True, "message": "迅雷秒传已关闭"}
        if not bool(getattr(self, "_viewing_enabled", False)) or not str(getattr(self, "_viewing_base_url", "") or ""):
            return [], {"provider": "viewing_xunlei", "enabled": False, "success": True, "message": "观影未启用"}
        session, login = self._viewing_session()
        if not login.get("success"):
            return [], {"provider": "viewing_xunlei", "enabled": True, **login}
        try:
            base_url = str(self._viewing_base_url).rstrip("/")
            search_url = f"{base_url}/s/1---1/{quote(str(keyword or '').strip())}"
            response = session.get(search_url, timeout=int(getattr(self, "_provider_timeout", 15) or 15))
            response.raise_for_status()
            parser = _GyingSearchParser()
            parser.feed(response.text or "")
            candidates: List[Dict[str, Any]] = []
            result_limit = int(getattr(self, "_provider_result_limit", 20) or 20)
            for item in parser.items[:result_limit]:
                href = str(item.get("href") or "").strip()
                title = str(item.get("title") or "").strip()
                if not href:
                    continue
                down_url = urljoin(base_url + "/", f"res/downurl{href}")
                detail = session.get(down_url, timeout=int(getattr(self, "_provider_timeout", 15) or 15), headers={"Referer": response.url})
                if detail.status_code >= 400:
                    continue
                try:
                    payload = detail.json()
                except Exception:
                    try:
                        payload = json.loads(detail.text or "{}")
                    except Exception:
                        continue
                panlist = payload.get("panlist") if isinstance(payload, dict) else None
                urls = list((panlist or {}).get("url") or []) if isinstance(panlist, dict) else []
                names = list((panlist or {}).get("name") or []) if isinstance(panlist, dict) else []
                for index, value in enumerate(urls):
                    label = str(names[index] if index < len(names) else title or "").strip()
                    for row in parse_xunlei_share(str(value), label=label or title):
                        row["search_title"] = title
                        candidates.append(row)
            dedup: Dict[str, Dict[str, Any]] = {}
            for row in candidates:
                key = str(row.get("share_id") or "")
                old = dedup.get(key)
                if not old or (not old.get("passcode") and row.get("passcode")):
                    dedup[key] = row
            rows = list(dedup.values())[:result_limit]
            return rows, {"provider": "viewing_xunlei", "enabled": True, "success": True, "message": f"观影找到 {len(rows)} 个迅雷分享候选", "login_mode": login.get("mode"), "cards": len(parser.items)}
        except Exception as err:
            return [], {"provider": "viewing_xunlei", "enabled": True, "success": False, "message": str(err)[:300], "login_mode": login.get("mode")}

    def _xunlei_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"Accept": "application/json;charset=UTF-8", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36", "Referer": "https://pan.xunlei.com/"})
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        return session

    def _refresh_xunlei_captcha(self, action: str) -> str:
        raw = str(self._xunlei_captcha_init_json or "").strip()
        if not raw:
            return ""
        try:
            payload = json.loads(raw)
        except Exception:
            return ""
        if not isinstance(payload, dict):
            return ""
        payload = dict(payload)
        if not payload.get("client_id"):
            payload["client_id"] = self._xunlei_client_id
        if not payload.get("device_id") and self._xunlei_device_id:
            payload["device_id"] = self._xunlei_device_id
        if action:
            payload["action"] = str(action)
        session = self._xunlei_session()
        try:
            response = session.post(XUNLEI_CAPTCHA_INIT, json=payload, timeout=int(getattr(self, "_provider_timeout", 15) or 15))
            body = response.json() if response.content else {}
            token = str((body or {}).get("captcha_token") or "").strip()
            if token:
                self._xunlei_runtime_captcha_token = token
                return token
            return ""
        except Exception:
            return ""

    def _xunlei_headers(self, action: str, *, refresh: bool = False) -> Dict[str, str]:
        token = "" if refresh else str(self._xunlei_runtime_captcha_token or self._xunlei_captcha_token or "").strip()
        if not token:
            token = self._refresh_xunlei_captcha(action)
        headers = {"Accept": "application/json;charset=UTF-8", "Content-Type": "application/json", "x-client-id": str(self._xunlei_client_id or XUNLEI_DEFAULT_CLIENT_ID), "Referer": "https://pan.xunlei.com/"}
        if self._xunlei_device_id:
            headers["x-device-id"] = self._xunlei_device_id
            headers["x-guid"] = self._xunlei_device_id
        if token:
            headers["x-captcha-token"] = token
        return headers

    @staticmethod
    def _xunlei_captcha_error(response: requests.Response, payload: Any) -> bool:
        text = ""
        if isinstance(payload, dict):
            text = " ".join(str(payload.get(key) or "") for key in ("error", "error_description", "message"))
        if not text:
            text = str(getattr(response, "text", "") or "")[:1000]
        return response.status_code in (400, 401, 403) and bool(re.search(r"captcha|device.*match|device_id.*empty", text, re.I))

    def _xunlei_get(self, endpoint: str, params: Dict[str, Any], *, action: str) -> Dict[str, Any]:
        session = self._xunlei_session()
        url = f"{XUNLEI_API_BASE}{endpoint}"
        last_error = ""
        for attempt in range(2):
            headers = self._xunlei_headers(action, refresh=attempt > 0)
            if not headers.get("x-captcha-token"):
                raise RuntimeError("迅雷 captcha_token 未配置；可填写 captcha_token，或粘贴 shield/captcha/init 请求体用于自动刷新")
            response = session.get(url, params=params, headers=headers, timeout=int(getattr(self, "_provider_timeout", 15) or 15))
            try:
                payload = response.json()
            except Exception:
                payload = {}
            if response.status_code < 400:
                return payload if isinstance(payload, dict) else {}
            last_error = str((payload or {}).get("error_description") or (payload or {}).get("error") or response.text or f"HTTP {response.status_code}")[:300]
            if attempt == 0 and self._xunlei_captcha_init_json and self._xunlei_captcha_error(response, payload):
                self._xunlei_runtime_captcha_token = ""
                continue
            break
        raise RuntimeError(f"迅雷分享接口失败：{last_error or 'unknown error'}")

    def _xunlei_share_info(self, share_id: str, passcode: str = "") -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": 100, "share_id": share_id}
        if passcode:
            params["pass_code"] = passcode
        body = self._xunlei_get("/drive/v1/share", params, action="get:/drive/v1/share")
        status = str(body.get("share_status") or "OK").upper()
        token = str(body.get("pass_code_token") or "").strip()
        if status not in {"", "OK"}:
            raise RuntimeError(str(body.get("share_status_text") or status))
        if not token:
            raise RuntimeError("迅雷分享未返回 pass_code_token；如分享有提取码，请确认观影资源中已包含正确提取码")
        return {"share_id": share_id, "pass_code_token": token, "title": str(body.get("title") or "").strip()}

    def _xunlei_normalize_file(self, raw: Dict[str, Any], path_prefix: str, parent_id: str) -> Dict[str, Any]:
        name = str(raw.get("name") or raw.get("file_name") or raw.get("filename") or "").strip()
        path = "/".join(part for part in (str(path_prefix or "").strip("/"), name) if part)
        gcid = str(raw.get("hash") or raw.get("gcid") or "").strip()
        md5 = str(raw.get("md5") or raw.get("file_md5") or "").strip()
        cid = str(raw.get("cid") or raw.get("content_hash") or "").strip()
        return {"id": str(raw.get("id") or raw.get("file_id") or "").strip(), "parent_id": str(raw.get("parent_id") or parent_id or "").strip(), "name": name, "path": path or name, "size": _safe_int(raw.get("size") or raw.get("file_size"), 0), "gcid": gcid.upper() if _HEX40_RE.match(gcid) else "", "md5": md5.lower() if _HEX32_RE.match(md5) else "", "cid": cid.lower() if _HEX40_RE.match(cid) and cid.lower() != gcid.lower() else "", "download_url": _pick_download_url(raw), "kind": str(raw.get("kind") or "")}

    def _xunlei_share_files(self, share_id: str, pass_code_token: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        queue: List[Tuple[str, str]] = [("", "")]
        visited = set()
        while queue and len(rows) < self._xunlei_flash_max_files:
            parent_id, prefix = queue.pop(0)
            if parent_id in visited:
                continue
            visited.add(parent_id)
            page_token = ""
            while len(rows) < self._xunlei_flash_max_files:
                body = self._xunlei_get("/drive/v1/share/detail", {"share_id": share_id, "parent_id": parent_id, "pass_code_token": pass_code_token, "limit": 100, "page_token": page_token, "with_audit": "true", "thumbnail_size": "SIZE_LARGE", "usage": "CONSUME"}, action="get:/drive/v1/share/detail")
                files = body.get("files") or (body.get("data") or {}).get("files") or []
                if not isinstance(files, list):
                    files = []
                for raw in files:
                    if not isinstance(raw, dict):
                        continue
                    if str(raw.get("kind") or "") == "drive#folder":
                        folder_name = str(raw.get("name") or "").strip()
                        sub_prefix = "/".join(part for part in (prefix.strip("/"), folder_name) if part)
                        queue.append((str(raw.get("id") or ""), sub_prefix))
                    else:
                        rows.append(self._xunlei_normalize_file(raw, prefix, parent_id))
                        if len(rows) >= self._xunlei_flash_max_files:
                            break
                page_token = str(body.get("next_page_token") or "").strip()
                if not page_token:
                    break
        return rows

    def _xunlei_file_info(self, share_id: str, pass_code_token: str, row: Dict[str, Any]) -> Dict[str, Any]:
        file_id = str(row.get("id") or "")
        if not file_id:
            return row
        body = self._xunlei_get("/drive/v1/share/file_info", {"share_id": share_id, "file_id": file_id, "pass_code_token": pass_code_token, "usage": "CONSUME"}, action="get:/drive/v1/share/file_info")
        info = body.get("file_info") if isinstance(body.get("file_info"), dict) else body
        normalized = self._xunlei_normalize_file(dict(info or {}), str(row.get("path") or "").rsplit("/", 1)[0], str(row.get("parent_id") or ""))
        merged = dict(row)
        for key in ("gcid", "md5", "cid", "download_url", "size"):
            if normalized.get(key):
                merged[key] = normalized[key]
        return merged

    def _xunlei_compute_triple_cid(self, download_url: str, file_size: int) -> str:
        if not download_url or file_size <= 0:
            return ""
        sample_size = 20 * 1024
        if file_size <= sample_size:
            ranges = [(0, file_size - 1)] * 3
        else:
            ranges = [(0, min(sample_size - 1, file_size - 1)), (file_size // 3, min(file_size // 3 + sample_size - 1, file_size - 1)), (max(0, file_size - sample_size), file_size - 1)]
        session = requests.Session()
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        chunks: List[bytes] = []
        for start, end in ranges:
            try:
                response = session.get(download_url, headers={"Range": f"bytes={start}-{end}", "Referer": "https://pan.xunlei.com/", "Origin": "https://pan.xunlei.com"}, timeout=int(getattr(self, "_provider_timeout", 15) or 15))
                if response.status_code not in (200, 206) or not response.content:
                    return ""
                content = bytes(response.content)
                expected = end - start + 1
                if response.status_code == 200 and len(content) == file_size:
                    content = content[start:end + 1]
                elif len(content) > expected:
                    content = content[:expected]
                if len(content) != expected:
                    return ""
                chunks.append(content)
            except Exception:
                return ""
        return hashlib.sha1(b"".join(chunks)).hexdigest()

    def _guangya_userres_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        client, _ = self._get_guangya_runtime()
        if not client:
            raise RuntimeError("光鸭云盘助手未运行或未登录")
        request = getattr(client, "_request", None)
        if not callable(request):
            raise RuntimeError("当前光鸭客户端缺少 userres 秒传请求能力")
        base_url = str(getattr(client, "API_BASE_URL", "https://api.guangyapan.com") or "https://api.guangyapan.com").rstrip("/")
        result = request(method="POST", url=f"{base_url}{endpoint}", data=dict(payload or {}))
        return result if isinstance(result, dict) else {"msg": "error", "error": str(result)}

    def _xunlei_target_parent(self, subscribe: Any, relative_path: str) -> Tuple[str, str]:
        target_path, root_parent_id = self._offline_target_parent(subscribe)
        parts = [part.strip() for part in str(relative_path or "").replace("\\", "/").split("/")[:-1] if part.strip() and part.strip() not in {".", ".."}]
        if not parts:
            return target_path, root_parent_id
        _, api = self._get_guangya_runtime()
        if not api:
            raise RuntimeError("光鸭存储运行时不可用")
        full_path = str(Path(target_path).joinpath(*parts)).replace("\\", "/")
        folder = api.get_folder(Path(full_path))
        if not folder:
            raise RuntimeError(f"无法创建光鸭秒传目标目录：{full_path}")
        return full_path, str(getattr(folder, "fileid", "") or "")

    @staticmethod
    def _guangya_task_id(body: Dict[str, Any]) -> str:
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            return str(data.get("taskId") or data.get("task_id") or "").strip()
        return ""

    def _poll_guangya_flash_task(self, task_id: str) -> bool:
        for index in range(30):
            body = self._guangya_userres_request("/userres/v1/file/get_info_by_task_id", {"taskId": str(task_id)})
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and (data.get("fileId") or data.get("fileid") or data.get("file_id")):
                return True
            time.sleep(0.25 if index < 4 else 0.45)
        return False

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        gcid = str(row.get("gcid") or "").strip().upper()
        size = _safe_int(row.get("size"), 0)
        if not _HEX40_RE.match(gcid) or size <= 0:
            return {"success": False, "reason": "缺少有效 GCID 或文件大小"}
        md5 = str(row.get("md5") or "").strip().lower()
        if not _HEX32_RE.match(md5):
            md5 = ""
        cid_candidates: List[str] = []
        raw_cid = str(row.get("cid") or "").strip().lower()
        if _HEX40_RE.match(raw_cid) and raw_cid != gcid.lower():
            cid_candidates.append(raw_cid)
        if row.get("download_url"):
            triple = self._xunlei_compute_triple_cid(str(row.get("download_url") or ""), size)
            if _HEX40_RE.match(triple) and triple != gcid.lower() and triple not in cid_candidates:
                cid_candidates.append(triple)
        _, parent_id = self._xunlei_target_parent(subscribe, str(row.get("path") or row.get("name") or ""))
        name = str(row.get("name") or str(row.get("path") or "").rsplit("/", 1)[-1] or "file").strip()
        token_candidates: List[Dict[str, Any]] = []
        for cid in cid_candidates:
            res = {"gcid": gcid, "cid": cid.upper(), "fileSize": size}
            if md5:
                res["md5"] = md5.upper()
            token_candidates.append(res)
        if md5:
            token_candidates.append({"gcid": gcid, "md5": md5.upper(), "fileSize": size})
        token_candidates.append({"gcid": gcid, "fileSize": size})
        task_id = ""
        used_res: Dict[str, Any] = {}
        last_error = ""
        for res in token_candidates:
            body = self._guangya_userres_request("/userres/v1/get_res_center_token", {"capacity": 2, "res": res, "name": name, "parentId": parent_id})
            code = body.get("code") if isinstance(body, dict) else None
            if code in (156, "156"):
                return {"success": True, "instant": True, "reason": "get_res_center_token code=156"}
            task_id = self._guangya_task_id(body)
            if task_id:
                used_res = res
                break
            last_error = str(body.get("msg") or body.get("message") or body.get("error") or code or "秒传令牌未命中")[:240]
        if not task_id:
            return {"success": False, "reason": last_error or "光鸭未创建秒传任务"}
        check_candidates: List[Dict[str, Any]] = []
        for cid in cid_candidates:
            item = {"taskId": task_id, "gcid": gcid, "cid": cid.upper(), "fileSize": size}
            if md5:
                item["md5"] = md5.upper()
            check_candidates.append(item)
        if used_res.get("cid"):
            item = {"taskId": task_id, "gcid": gcid, "cid": used_res["cid"], "fileSize": size}
            if md5:
                item["md5"] = md5.upper()
            check_candidates.append(item)
        if md5:
            check_candidates.append({"taskId": task_id, "gcid": gcid, "md5": md5.upper(), "fileSize": size})
        accepted_task = ""
        for check in check_candidates:
            body = self._guangya_userres_request("/userres/v1/check_can_flash_upload", check)
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and data.get("canFlashUpload") is True:
                accepted_task = str(data.get("taskId") or task_id)
                break
            candidate_task = self._guangya_task_id(body)
            if candidate_task:
                accepted_task = candidate_task
                break
        if accepted_task and self._poll_guangya_flash_task(accepted_task):
            return {"success": True, "instant": True, "task_id": accepted_task, "reason": "光鸭秒传完成"}
        try:
            self._guangya_userres_request("/userres/v1/file/delete_upload_task", {"taskIds": [accepted_task or task_id]})
        except Exception:
            pass
        return {"success": False, "task_id": accepted_task or task_id, "reason": "光鸭秒传未命中；不做 OSS/本地中转，回退下一来源"}

    def _xunlei_state(self) -> Dict[str, Any]:
        state = self.get_data("xunlei_flash_state") or {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("schema", 1)
        state.setdefault("items", {})
        return state

    def _save_xunlei_state(self, state: Dict[str, Any]) -> None:
        items = state.get("items") or {}
        if isinstance(items, dict) and len(items) > 2000:
            ordered = sorted(items.items(), key=lambda pair: float((pair[1] or {}).get("updated_ts") or 0), reverse=True)[:2000]
            state["items"] = dict(ordered)
        self.save_data("xunlei_flash_state", state)

    @staticmethod
    def _xunlei_item_key(subscribe_id: int, share_id: str, row: Dict[str, Any]) -> str:
        raw = f"{int(subscribe_id or 0)}|{share_id}|{row.get('id') or ''}|{row.get('gcid') or ''}|{row.get('path') or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _xunlei_file_episodes(self, subscribe: Any, row: Dict[str, Any], package_paths: Optional[Iterable[str]] = None) -> set[int]:
        if self._is_movie_subscription(subscribe) or not _is_video(str(row.get("path") or row.get("name") or "")):
            return set()
        result = resolve_episode(
            str(row.get("path") or row.get("name") or ""),
            package_paths=package_paths,
            season_hint=getattr(subscribe, "season", None),
        )
        return reliable_episode_set(result, float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE))

    @staticmethod
    def _xunlei_movie_primary_index_v1119(files: List[Dict[str, Any]], indexes: Iterable[int]) -> Optional[int]:
        """电影以分享内最大的有效视频作为正片，花絮失败不能触发 Magnet 回退。"""
        videos = [
            int(index) for index in indexes
            if 0 <= int(index) < len(files)
            and _is_video(str(files[int(index)].get("path") or files[int(index)].get("name") or ""))
        ]
        return max(videos, key=lambda index: _safe_int(files[index].get("size"), 0)) if videos else None

    @staticmethod
    def _xunlei_movie_feature_indexes_v1122(files: List[Dict[str, Any]], indexes: Iterable[int]) -> set[int]:
        """严格匹配电影分享后，任一非片头/预告/样片视频都可作为正片完成证据。"""
        return {
            int(index) for index in indexes
            if 0 <= int(index) < len(files)
            and _is_video(str(files[int(index)].get("path") or files[int(index)].get("name") or ""))
            and not is_auxiliary_media_v1105(str(files[int(index)].get("path") or files[int(index)].get("name") or ""))
            and _safe_int(files[int(index)].get("size"), 0) > 0
        }

    def _xunlei_json_identity_matches_v1123(
        self,
        subscribe: Any,
        candidate: Dict[str, Any],
        info: Dict[str, Any],
        template: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """搜索卡片只负责发现；迅雷标题与 JSON 路径负责最终媒体身份门禁。"""
        expected_raw = str(getattr(subscribe, "name", "") or "").strip()
        expected = _normalize_media_text(expected_raw)
        file_paths = [str(row.get("path") or "") for row in (template.get("files") or []) if isinstance(row, dict)]
        identity_raw = " ".join(
            value for value in (
                str(info.get("title") or "").strip(),
                str(candidate.get("name") or "").strip(),
                " ".join(file_paths[:20]),
            ) if value
        )
        actual = _normalize_media_text(identity_raw)
        if not expected or not actual:
            return False, "迅雷 JSON 缺少可校验的媒体标题/路径"
        direct_match = expected in actual or actual in expected
        expected_cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", expected_raw))
        actual_cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", identity_raw))
        if expected_cjk and actual_cjk and not direct_match:
            return False, f"迅雷 JSON 实际媒体不匹配：期望={expected_raw} 实际={identity_raw[:180]}"

        expected_year = str(getattr(subscribe, "year", "") or "").strip()
        years = set(re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", identity_raw))
        if expected_year and years and expected_year not in years:
            return False, f"迅雷 JSON 年份不匹配：期望={expected_year} 实际={','.join(sorted(years))}"

        try:
            expected_season = int(getattr(subscribe, "season", 0) or 0)
        except (TypeError, ValueError):
            expected_season = 0
        seasons = {int(value) for value in re.findall(r"(?i)\bS(?:eason)?[ ._-]*0*(\d{1,2})\b", identity_raw)}
        if expected_season > 0 and seasons and expected_season not in seasons:
            return False, f"迅雷 JSON 季号不匹配：期望=S{expected_season:02d} 实际={sorted(seasons)}"

        search_title = _normalize_media_text(candidate.get("search_title") or "")
        if not direct_match and not (search_title and (expected in search_title or search_title in expected)):
            return False, f"迅雷 JSON 无法确认属于当前媒体：{identity_raw[:180]}"
        return True, "迅雷 JSON 标题/年份/季号校验通过"

    def _select_xunlei_files(self, subscribe: Any, files: List[Dict[str, Any]], target_episodes: Iterable[int]) -> Dict[str, Any]:
        fake_subfiles = [{"fileIndex": index, "fileName": str(row.get("path") or row.get("name") or ""), "fileSize": _safe_int(row.get("size"), 0)} for index, row in enumerate(files)]
        source = {"type": "xunlei", "target_episodes": sorted(set(int(v) for v in target_episodes if int(v or 0) > 0))}
        return self._planner_file_selection(source, subscribe, {"btResInfo": {"subfiles": fake_subfiles}})

    @staticmethod
    def _xunlei_json_batch_indexes_v1118(files: List[Dict[str, Any]]) -> List[int]:
        """按稳定脚本把已匹配分享中的全部媒体文件写入 JSON。"""
        indexes: List[int] = []
        for index, row in enumerate(files or []):
            path = str((row or {}).get("path") or (row or {}).get("name") or "")
            if _is_video(path) or _is_subtitle(path):
                indexes.append(index)
        return indexes

    def _xunlei_reservation(self, subscribe_id: int) -> Dict[str, Any]:
        return dict(self._xunlei_runtime_reservations.get(int(subscribe_id or 0)) or {"episodes": set(), "paths": set(), "movie": False})

    def _pending_reservations(self, subscribe: Any, exclude_job_key: str = "") -> Dict[str, Any]:
        base = super()._pending_reservations(subscribe, exclude_job_key=exclude_job_key)
        sid = int(getattr(subscribe, "id", 0) or 0)
        extra = self._xunlei_reservation(sid)
        merged = dict(base or {})
        merged["episodes"] = set((base or {}).get("episodes") or set()).union(set(extra.get("episodes") or set()))
        merged["paths"] = set((base or {}).get("paths") or set()).union(set(extra.get("paths") or set()))
        merged["movie"] = bool((base or {}).get("movie")) or bool(extra.get("movie"))
        return merged

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        if not self._xunlei_flash_enabled or not bool(getattr(self, "_provider_auto_search", True)):
            return {"success": False, "handled": False, "message": "迅雷秒传预检已关闭"}
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return {"success": False, "handled": False, "message": "订阅 ID 无效"}
        is_movie = self._is_movie_subscription(subscribe)
        missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe) or []) if int(v or 0) > 0)
        candidates, state = self._search_viewing_xunlei(self._provider_keyword(subscribe))
        if not candidates:
            return {"success": False, "handled": False, "message": str(state.get("message") or "观影没有迅雷分享候选")}
        runtime = self._xunlei_reservation(sid)
        state_store = self._xunlei_state()
        saved_items = state_store["items"]
        successful_files = 0
        attempted_files = 0
        tried_shares = 0
        errors: List[str] = []
        for candidate in candidates:
            if not self._provider_candidate_matches(subscribe, candidate):
                continue
            tried_shares += 1
            share_id = str(candidate.get("share_id") or candidate.get("identity") or "")
            try:
                info = self._xunlei_share_info(share_id, str(candidate.get("passcode") or ""))
                files = self._xunlei_share_files(share_id, str(info.get("pass_code_token") or ""))
                enriched: List[Dict[str, Any]] = []
                for row in files:
                    path = str(row.get("path") or row.get("name") or "")
                    if bool(getattr(self, "_media_only", True)) and not (_is_video(path) or _is_subtitle(path)):
                        continue
                    # 稳定脚本极速模式：列表已给 GCID/size 时直接生成 JSON。
                    # cid/downloadUrl 允许为空，不能因此对 11 个文件逐个补详情。
                    if not row.get("gcid") or _safe_int(row.get("size"), 0) <= 0:
                        try:
                            row = self._xunlei_file_info(share_id, str(info.get("pass_code_token") or ""), row)
                        except Exception as err:
                            errors.append(f"{path}: {err}")
                    enriched.append(row)
                if not enriched:
                    continue
                descriptor = str(candidate.get("search_title") or candidate.get("name") or info.get("title") or "")
                allowed, reason = self._subscription_resource_allowed(subscribe, {"text": descriptor}, {"files": [{"relative_path": str(row.get("path") or ""), "name": str(row.get("name") or "")} for row in enriched]})
                if not allowed:
                    errors.append(f"{share_id}: 订阅规则不匹配 {reason}")
                    continue
                target = set() if is_movie else (missing - set(runtime.get("episodes") or set()))
                if not is_movie and not target:
                    break
                selection = self._select_xunlei_files(subscribe, enriched, target)
                planned_indexes = [int(v) for v in (selection.get("indexes") or [])]
                indexes = self._xunlei_json_batch_indexes_v1118(enriched)
                if not indexes:
                    errors.append(f"{share_id}: 迅雷分享中没有可写入 JSON 的视频/字幕文件")
                    continue
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【迅雷JSON】完整分享批次：share=%s files=%s planner=%s ambiguous=%s；缺集规划仅用于覆盖判断，不裁剪 JSON 文件",
                    share_id[:24], len(indexes), len(planned_indexes), bool(selection.get("ambiguous")),
                )
                batch_rows = [dict(enriched[idx] or {}) for idx in indexes]
                batch_template = self._xunlei_make_json_v1117(batch_rows)
                if len(batch_template.get("files") or []) != len(batch_rows):
                    errors.append(f"{share_id}: 迅雷完整分享 JSON 生成不完整")
                    continue
                identity_ok, identity_reason = self._xunlei_json_identity_matches_v1123(
                    subscribe, candidate, info, batch_template,
                )
                if not identity_ok:
                    errors.append(f"{share_id}: {identity_reason}")
                    self._plugin_log(
                        "WARNING",
                        "【光鸭转存助手】【迅雷JSON】整批拒绝导入：share=%s reason=%s",
                        share_id[:24], identity_reason[:360],
                    )
                    continue
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【迅雷JSON】整批身份校验通过：share=%s files=%s reason=%s",
                    share_id[:24], len(batch_rows), identity_reason,
                )
                selected_videos = [idx for idx in indexes if 0 <= idx < len(enriched) and _is_video(str(enriched[idx].get("path") or enriched[idx].get("name") or ""))]
                package_paths = [str(enriched[idx].get("path") or enriched[idx].get("name") or "") for idx in selected_videos]
                movie_primary = self._xunlei_movie_primary_index_v1119(enriched, indexes) if is_movie else None
                movie_features = self._xunlei_movie_feature_indexes_v1122(enriched, indexes) if is_movie else set()
                successful_indexes: set[int] = set()
                video_success = 0
                skip_batch_indexes: set[int] = set()
                for batch_index, index in enumerate(indexes):
                    row = enriched[index]
                    item_key = self._xunlei_item_key(sid, share_id, row)
                    if str((saved_items.get(item_key) or {}).get("state") or "") == "completed":
                        skip_batch_indexes.add(batch_index)
                batch_import = self._xunlei_import_json_batch_v1123(
                    subscribe,
                    batch_template,
                    batch_rows,
                    skip_indexes=skip_batch_indexes,
                )
                batch_results = {
                    int(item.get("index") or 0): dict(item.get("result") or {})
                    for item in (batch_import.get("results") or [])
                    if isinstance(item, dict)
                }
                for batch_index, index in enumerate(indexes):
                    if index < 0 or index >= len(enriched):
                        continue
                    row = enriched[index]
                    item_key = self._xunlei_item_key(sid, share_id, row)
                    previous = dict(saved_items.get(item_key) or {})
                    row_episodes = self._xunlei_file_episodes(subscribe, row, package_paths=package_paths)
                    if str(previous.get("state") or "") == "completed":
                        successful_files += 1
                        if _is_video(str(row.get("path") or row.get("name") or "")):
                            video_success += 1
                            successful_indexes.add(index)
                            runtime["episodes"] = set(runtime.get("episodes") or set()).union(row_episodes)
                        continue
                    attempted_files += 1
                    if not row.get("gcid"):
                        errors.append(f"{row.get('path')}: 迅雷未提供 GCID")
                        continue
                    result = dict(batch_results.get(batch_index) or {"success": False, "reason": "迅雷 JSON 批次未返回文件结果"})
                    saved_items[item_key] = {"state": "completed" if result.get("success") else "failed", "subscribe_id": sid, "share_id": share_id, "file_id": str(row.get("id") or ""), "path": str(row.get("path") or "")[:500], "gcid": str(row.get("gcid") or ""), "episodes": sorted(row_episodes), "message": str(result.get("reason") or "")[:300], "updated_at": self._now_text(), "updated_ts": time.time()}
                    self._save_xunlei_state(state_store)
                    if result.get("success"):
                        successful_files += 1
                        if _is_video(str(row.get("path") or row.get("name") or "")):
                            video_success += 1
                            successful_indexes.add(index)
                            runtime["episodes"] = set(runtime.get("episodes") or set()).union(row_episodes)
                    else:
                        errors.append(f"{row.get('path')}: {result.get('reason')}")
                completed_movie_indexes = movie_features.intersection(successful_indexes)
                if is_movie and completed_movie_indexes:
                    runtime["movie"] = True
                    completed_names = [
                        str(enriched[index].get("path") or enriched[index].get("name") or "")[:180]
                        for index in sorted(completed_movie_indexes)
                    ]
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【迅雷秒传】#%s 电影正片已确认成功/已存在：%s；立即阻断光鸭分享/Magnet/ED2K",
                        sid,
                        "、".join(completed_names[:3]) or "已匹配视频",
                    )
                    break
                if not is_movie and missing and missing.issubset(set(runtime.get("episodes") or set())):
                    break
            except Exception as err:
                errors.append(f"{share_id}: {str(err)[:240]}")
                continue
        self._xunlei_runtime_reservations[sid] = runtime
        completed_episodes = sorted(set(runtime.get("episodes") or set()))
        if completed_episodes:
            try:
                self._remember_episode_facts(subscribe, completed_episodes, origin="viewing_xunlei_flash")
                self._sync_media_facts_progress(subscribe)
            except Exception:
                pass
        fully_handled = bool(runtime.get("movie")) if is_movie else bool(missing and missing.issubset(set(completed_episodes)))
        if fully_handled:
            self._plugin_log("INFO", "【光鸭转存助手】【迅雷秒传】#%s 观影迅雷分享已最高优先级覆盖目标，跳过光鸭分享/Magnet/ED2K", sid)
        return {"success": successful_files > 0, "handled": fully_handled, "priority": 0, "shares": tried_shares, "attempted_files": attempted_files, "successful_files": successful_files, "episodes": completed_episodes, "movie": bool(runtime.get("movie")), "errors": errors[:20], "message": (f"迅雷秒传成功 {successful_files} 个文件" + (f"，覆盖 E{','.join(str(v) for v in completed_episodes)}" if completed_episodes else "")) if successful_files else "观影迅雷候选未命中光鸭秒传，继续下一来源"}

    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        self._xunlei_runtime_reservations[sid] = {"episodes": set(), "paths": set(), "movie": False}
        try:
            try:
                flash = self._dispatch_xunlei_flash(subscribe)
            except Exception as err:
                self._plugin_log("WARNING", "【光鸭转存助手】【迅雷秒传】#%s 预检失败，回退后续来源：%s", sid, err)
                flash = {"success": False, "handled": False, "message": str(err)}
            if flash.get("handled"):
                return {"success": True, "handled": True, "xunlei_flash": flash, "message": f"观影迅雷分享秒传优先完成；{flash.get('message')}"}
            lower = super()._try_transfer_subscription_inner(subscribe, force=force, refresh_channel=refresh_channel)
            if flash.get("success"):
                return {**dict(lower or {}), "xunlei_flash": flash, "message": f"{flash.get('message')}；{str((lower or {}).get('message') or '已检查后续来源')}"}
            return lower
        finally:
            self._xunlei_runtime_reservations.pop(sid, None)

    def api_xunlei_flash_test(self, share_url: str = "", passcode: str = "") -> Dict[str, Any]:
        parsed = parse_xunlei_share(str(share_url or ""), label="test")
        if not parsed:
            return {"success": False, "message": "请输入有效的 https://pan.xunlei.com/s/... 分享链接"}
        row = parsed[0]
        if passcode:
            row["passcode"] = str(passcode).strip()
        try:
            info = self._xunlei_share_info(str(row.get("share_id") or ""), str(row.get("passcode") or ""))
            files = self._xunlei_share_files(str(row.get("share_id") or ""), str(info.get("pass_code_token") or ""))
            return {"success": True, "message": f"迅雷分享可读，共发现 {len(files)} 个文件", "data": {"share_id": str(row.get("share_id") or ""), "title": str(info.get("title") or ""), "files": len(files), "with_captcha": bool(self._xunlei_runtime_captcha_token or self._xunlei_captcha_token or self._xunlei_captcha_init_json)}}
        except Exception as err:
            return {"success": False, "message": str(err)[:500]}

    def api_xunlei_flash_state(self) -> Dict[str, Any]:
        state = self._xunlei_state()
        rows = []
        for item in (state.get("items") or {}).values():
            if not isinstance(item, dict):
                continue
            rows.append({"state": str(item.get("state") or ""), "subscribe_id": int(item.get("subscribe_id") or 0), "share_id": str(item.get("share_id") or "")[:20], "path": str(item.get("path") or "")[:300], "episodes": list(item.get("episodes") or []), "message": str(item.get("message") or "")[:300], "updated_at": str(item.get("updated_at") or "")})
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {"success": True, "count": len(rows), "data": rows[:100]}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        if "/xunlei/flash/test" not in paths:
            apis.append({"path": "/xunlei/flash/test", "endpoint": self.api_xunlei_flash_test, "methods": ["POST"], "summary": "测试迅雷分享读取"})
        if "/xunlei/flash/state" not in paths:
            apis.append({"path": "/xunlei/flash/state", "endpoint": self.api_xunlei_flash_state, "methods": ["GET"], "summary": "查看迅雷秒传状态"})
        return apis


__all__ = ["GuangYaXunleiFlashMixin", "parse_xunlei_share"]
