"""光鸭云盘助手 V4 alpha1。

本文件是 MoviePilot V3 原生接口重构基线：
- 单一可读 __init__.py，不再使用 JSON 虚拟模块、Finder/Loader 或版本补丁链；
- 插件侧优先使用 app.sdk.* 稳定门面；
- 当前 alpha1 先收口认证、存储、上传下载、WebDAV 与流式代理；
- 自动整理将在同一分支按 ResourceStore -> Scanner -> Organizer 重新实现。
"""


# =============================================================================
# OSS native upload
# =============================================================================

"""v3.5.7：仅依赖 MoviePilot 自带 requests 的 OSS STS 分片上传。

V3 插件不再安装 oss2。这里直接实现 OSS REST Multipart Upload 的最小合同：
InitiateMultipartUpload -> UploadPart -> CompleteMultipartUpload；失败时 Abort。

鉴权使用 OSS V1 Header Signature。光鸭返回的是 STS 临时凭证，因此
``x-oss-security-token`` 既发送到 OSS，也参与 CanonicalizedOSSHeaders。
"""

import base64
import hashlib
import hmac
from email.utils import formatdate
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET


PART_SIZE = 5 * 1024 * 1024


def _normalize_endpoint(endpoint: str, bucket_name: str) -> Tuple[str, str]:
    """返回 ``(base_url, host)``，强制使用 OSS virtual-hosted style。"""
    value = str(endpoint or "").strip()
    if not value:
        raise ValueError("OSS endpoint 为空")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or parsed.path
    host = host.strip().strip("/")
    if not host:
        raise ValueError("OSS endpoint 无法解析")
    bucket = str(bucket_name or "").strip()
    if not bucket:
        raise ValueError("OSS bucket 为空")
    if host.casefold() != bucket.casefold() and not host.casefold().startswith(f"{bucket.casefold()}."):
        host = f"{bucket}.{host}"
    return f"{scheme}://{host}", host


def _object_url_path(object_path: str) -> Tuple[str, str]:
    """返回签名使用的原始 key 与 HTTP URL 编码路径。"""
    key = str(object_path or "").lstrip("/")
    if not key:
        raise ValueError("OSS object path 为空")
    return key, "/" + quote(key, safe="/~")


def _query_string(params: Sequence[Tuple[str, Optional[str]]]) -> str:
    """构造 OSS 子资源查询串；无值子资源保持 ``?uploads`` 而不是 ``?uploads=``。"""
    parts = []
    for key, value in sorted(params, key=lambda item: item[0]):
        encoded_key = quote(str(key), safe="-_.~")
        if value is None:
            parts.append(encoded_key)
        else:
            parts.append(f"{encoded_key}={quote(str(value), safe='-_.~')}")
    return "&".join(parts)


def _canonical_resource(
    bucket_name: str,
    object_key: str,
    subresources: Sequence[Tuple[str, Optional[str]]] = (),
) -> str:
    resource = f"/{bucket_name}/{object_key}"
    query = _query_string(subresources)
    return f"{resource}?{query}" if query else resource


def _canonical_oss_headers(headers: Mapping[str, str]) -> str:
    rows = []
    for key, value in headers.items():
        lowered = str(key).strip().casefold()
        if not lowered.startswith("x-oss-"):
            continue
        normalized = " ".join(str(value or "").strip().split())
        rows.append((lowered, normalized))
    rows.sort(key=lambda item: item[0])
    return "".join(f"{key}:{value}\n" for key, value in rows)


def _content_md5(body: bytes) -> str:
    return base64.b64encode(hashlib.md5(body).digest()).decode("ascii")  # noqa: S324 - OSS API requires MD5 header


def _authorization(
    *,
    method: str,
    access_key_id: str,
    access_key_secret: str,
    date: str,
    canonical_resource: str,
    headers: Mapping[str, str],
    content_md5: str = "",
    content_type: str = "",
) -> str:
    string_to_sign = (
        f"{method.upper()}\n{content_md5}\n{content_type}\n{date}\n"
        f"{_canonical_oss_headers(headers)}{canonical_resource}"
    )
    digest = hmac.new(
        str(access_key_secret).encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return f"OSS {access_key_id}:{signature}"


def _signed_headers(
    *,
    method: str,
    access_key_id: str,
    access_key_secret: str,
    security_token: str,
    canonical_resource: str,
    body: bytes = b"",
    content_type: str = "",
) -> dict[str, str]:
    date = formatdate(usegmt=True)
    headers: dict[str, str] = {
        "Date": date,
        "x-oss-security-token": str(security_token or ""),
    }
    md5_value = _content_md5(body) if body else ""
    if md5_value:
        headers["Content-MD5"] = md5_value
    if content_type:
        headers["Content-Type"] = content_type
    headers["Authorization"] = _authorization(
        method=method,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        date=date,
        canonical_resource=canonical_resource,
        headers=headers,
        content_md5=md5_value,
        content_type=content_type,
    )
    return headers


def _xml_text(payload: bytes, local_name: str) -> str:
    root = ET.fromstring(payload)
    for element in root.iter():
        name = str(element.tag).rsplit("}", 1)[-1]
        if name == local_name and element.text:
            return element.text.strip()
    return ""


def _complete_xml(parts: Iterable[Tuple[int, str]]) -> bytes:
    root = ET.Element("CompleteMultipartUpload")
    for part_number, etag in parts:
        part = ET.SubElement(root, "Part")
        ET.SubElement(part, "PartNumber").text = str(part_number)
        ET.SubElement(part, "ETag").text = str(etag)
    return ET.tostring(root, encoding="utf-8", xml_declaration=False)


def upload_file_multipart(
    *,
    endpoint: str,
    bucket_name: str,
    object_path: str,
    file_path: str,
    oss_access_key_id: str,
    oss_access_key_secret: str,
    security_token: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    part_size: int = PART_SIZE,
    timeout: int = 120,
) -> Optional[str]:
    """使用 OSS REST API 完成 STS 分片上传，成功返回 ETag/RequestId。"""
    # requests 是 MoviePilot 主程序自身依赖；这里懒加载，避免把它变成插件安装清单。
    import requests

    source = Path(file_path)
    total_size = int(source.stat().st_size)
    if total_size < 0:
        raise ValueError("文件大小无效")
    part_size = max(int(part_size or PART_SIZE), 100 * 1024)

    base_url, _host = _normalize_endpoint(endpoint, bucket_name)
    object_key, url_path = _object_url_path(object_path)
    object_url = f"{base_url}{url_path}"
    upload_id = ""

    def request(
        method: str,
        subresources: Sequence[Tuple[str, Optional[str]]],
        *,
        body: bytes = b"",
        content_type: str = "",
    ):
        canonical = _canonical_resource(bucket_name, object_key, subresources)
        headers = _signed_headers(
            method=method,
            access_key_id=oss_access_key_id,
            access_key_secret=oss_access_key_secret,
            security_token=security_token,
            canonical_resource=canonical,
            body=body,
            content_type=content_type,
        )
        query = _query_string(subresources)
        url = f"{object_url}?{query}" if query else object_url
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body if body else None,
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    try:
        init_response = request("POST", (("uploads", None),))
        upload_id = _xml_text(init_response.content, "UploadId")
        if not upload_id:
            raise RuntimeError("OSS 初始化分片上传未返回 UploadId")

        parts: list[Tuple[int, str]] = []
        consumed = 0
        with source.open("rb") as stream:
            part_number = 1
            while True:
                chunk = stream.read(part_size)
                if not chunk:
                    break
                part_response = request(
                    "PUT",
                    (("partNumber", str(part_number)), ("uploadId", upload_id)),
                    body=chunk,
                    content_type="application/octet-stream",
                )
                etag = str(part_response.headers.get("ETag") or "").strip()
                if not etag:
                    raise RuntimeError(f"OSS 第 {part_number} 分片未返回 ETag")
                parts.append((part_number, etag))
                consumed += len(chunk)
                if callable(progress_callback):
                    progress_callback(consumed, total_size)
                part_number += 1

        # 空文件也需要一个有效 part。OSS UploadPart 不接受空 body，因此退化为普通 PUT。
        if not parts and total_size == 0:
            abort_headers = _signed_headers(
                method="DELETE",
                access_key_id=oss_access_key_id,
                access_key_secret=oss_access_key_secret,
                security_token=security_token,
                canonical_resource=_canonical_resource(
                    bucket_name, object_key, (("uploadId", upload_id),)
                ),
            )
            requests.delete(
                f"{object_url}?{_query_string((('uploadId', upload_id),))}",
                headers=abort_headers,
                timeout=timeout,
            )
            upload_id = ""
            put_response = request("PUT", (), body=b"", content_type="application/octet-stream")
            if callable(progress_callback):
                progress_callback(0, 0)
            return str(put_response.headers.get("ETag") or put_response.headers.get("x-oss-request-id") or "ok")

        complete_body = _complete_xml(parts)
        complete_response = request(
            "POST",
            (("uploadId", upload_id),),
            body=complete_body,
            content_type="application/xml",
        )
        upload_id = ""
        etag = _xml_text(complete_response.content, "ETag")
        return str(etag or complete_response.headers.get("ETag") or complete_response.headers.get("x-oss-request-id") or "ok")
    except Exception:
        if upload_id:
            try:
                request("DELETE", (("uploadId", upload_id),))
            except Exception:
                pass
        raise


__all__ = [
    "PART_SIZE",
    "_authorization",
    "_canonical_oss_headers",
    "_canonical_resource",
    "_complete_xml",
    "_normalize_endpoint",
    "_object_url_path",
    "_query_string",
    "_signed_headers",
    "upload_file_multipart",
]

# =============================================================================
# GuangYa HTTP client legacy core
# =============================================================================

_native_oss_multipart_upload = upload_file_multipart

"""光鸭云盘 HTTP 客户端。"""

import uuid
from typing import Any, Callable, Dict, Optional

import requests

from app.sdk.logging import logger
class _LegacyGuangYaClient:
    """光鸭云盘 HTTP 客户端。"""

    ACCOUNT_BASE_URL = "https://account.guangyapan.com"
    API_BASE_URL = "https://api.guangyapan.com"
    DEFAULT_CLIENT_ID = "aMe-8VSlkrbQXpUR"

    @staticmethod
    def _mask_token(token: Optional[str], keep: int = 10) -> str:
        if not token:
            return ""
        token = str(token)
        if len(token) <= keep * 2:
            return token
        return f"{token[:keep]}...{token[-keep:]}"

    def __init__(
        self,
        access_token: str = None,
        refresh_token: str = None,
        client_id: str = None,
        device_id: str = None,
        on_token_refresh: Callable[[str, str], None] = None,
    ):
        self._access_token = (access_token or "").strip()
        self._refresh_token = (refresh_token or "").strip()
        self._client_id = (client_id or self.DEFAULT_CLIENT_ID).strip() or self.DEFAULT_CLIENT_ID
        self._device_id = self._normalize_device_id(device_id) or self._generate_device_id()
        self._on_token_refresh = on_token_refresh
        self._last_refresh_attempted = False
        self._last_refresh_invalid = False
        self._last_refresh_result: Dict[str, Any] = {}
        self._session = requests.Session()
        self._session.headers.update(self._build_common_headers())

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def last_refresh_attempted(self) -> bool:
        return self._last_refresh_attempted

    @property
    def last_refresh_invalid(self) -> bool:
        return self._last_refresh_invalid

    @property
    def last_refresh_result(self) -> Dict[str, Any]:
        return self._last_refresh_result

    @staticmethod
    def _generate_device_id() -> str:
        return uuid.uuid4().hex

    @staticmethod
    def _normalize_device_id(device_id: Optional[str]) -> str:
        if not device_id:
            return ""
        return str(device_id).replace("-", "").strip()

    def _build_common_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://www.guangyupan.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN",
            "X-Client-Id": self._client_id,
            "X-Client-Version": "0.0.1",
            "X-Device-Id": self._device_id,
            "X-Device-Model": "chrome%2F147.0.0.0",
            "X-Device-Name": "PC-Chrome",
            "X-Device-Sign": f"wdi10.{self._device_id}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "X-Net-Work-Type": "NONE",
            "X-Os-Version": "Win32",
            "X-Platform-Version": "1",
            "X-Protocol-Version": "301",
            "X-Provider-Name": "NONE",
            "X-Sdk-Version": "9.0.2",
        }

    @staticmethod
    def _is_auth_invalid_result(result: Dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        combined = " ".join([
            str(result.get("error") or ""),
            str(result.get("msg") or ""),
            str(result.get("error_description") or ""),
            str(result),
        ]).lower()
        keywords = (
            "unauthenticated", "无效token", "authorize failed", "认证失败",
            "invalid_grant", "invalid token", "invalid_token", "token expiry",
        )
        return any(keyword.lower() in combined for keyword in keywords)

    def _get_auth_headers(self, use_access_token: bool = True) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Did": self._device_id,
            "Dt": "4",
            "did": self._device_id,
            "dt": "4",
        }
        if use_access_token and self._access_token:
            headers["accessToken"] = self._access_token
        return headers

    def _request(
        self,
        method: str,
        url: str,
        data: dict = None,
        headers: dict = None,
        need_auth: bool = True,
        retry_on_401: bool = True,
        treat_http_error_as_response: bool = False,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        req_headers = self._session.headers.copy()
        if headers:
            req_headers.update(headers)
        if need_auth and self._access_token:
            req_headers.update(self._get_auth_headers())

        if need_auth:
            logger.debug(
                "【光鸭云盘助手】发起请求: %s %s, device_id=%s, authenticated=%s",
                method.upper(), url, self._device_id, bool(self._access_token),
            )

        try:
            method_upper = method.upper()
            if method_upper == "GET":
                response = self._session.get(url, headers=req_headers, params=data, timeout=timeout)
            elif method_upper == "PUT":
                response = self._session.put(url, headers=req_headers, data=data, timeout=timeout)
            else:
                response = self._session.post(url, headers=req_headers, json=data, timeout=timeout)
            response.raise_for_status()
            if not response.text:
                return {"msg": "success", "code": 0}
            return response.json()
        except requests.exceptions.HTTPError as err:
            status_code = err.response.status_code if err.response is not None else None
            if treat_http_error_as_response and err.response is not None:
                try:
                    return err.response.json()
                except Exception:
                    return {
                        "msg": "error",
                        "code": status_code or -1,
                        "error": err.response.text[:500] if err.response.text else str(err),
                    }
            if status_code == 401 and retry_on_401 and need_auth:
                logger.info("【光鸭云盘助手】Token 失效，尝试刷新: device_id=%s", self._device_id)
                if self.refresh_access_token():
                    return self._request(
                        method=method,
                        url=url,
                        data=data,
                        headers=headers,
                        need_auth=need_auth,
                        retry_on_401=False,
                        treat_http_error_as_response=treat_http_error_as_response,
                        timeout=timeout,
                    )
            detail = f"{status_code} {err.response.reason}" if err.response is not None else str(err)
            try:
                if err.response is not None and err.response.text:
                    detail = f"{detail} - {err.response.text[:500]}"
            except Exception:
                pass
            logger.error("【光鸭云盘助手】请求失败: %s - %s", url, detail)
            return {"msg": "error", "code": -1, "error": detail}
        except requests.exceptions.RequestException as err:
            logger.error("【光鸭云盘助手】请求失败: %s - %s", url, err)
            return {"msg": "error", "code": -1, "error": str(err)}

    def get_device_code(self) -> Optional[Dict[str, Any]]:
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/device/code",
            data={"scope": "user", "client_id": self._client_id},
            need_auth=False,
        )
        if result.get("error"):
            return None
        return result

    def poll_device_code(self, device_code: str) -> Optional[Dict[str, Any]]:
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": self._client_id,
            },
            need_auth=False,
            treat_http_error_as_response=True,
        )
        if result.get("error") == "authorization_pending":
            return {"waiting": True, "message": "等待扫码中..."}
        if result.get("access_token"):
            self._access_token = result.get("access_token") or ""
            self._refresh_token = result.get("refresh_token") or ""
            return result
        return None

    def refresh_access_token(self) -> bool:
        self._last_refresh_attempted = True
        self._last_refresh_invalid = False
        self._last_refresh_result = {}
        if not self._refresh_token:
            self._last_refresh_invalid = True
            self._last_refresh_result = {"error": "missing_refresh_token", "msg": "refresh_token 为空"}
            logger.warning("【光鸭云盘助手】刷新失败：refresh_token 为空")
            return False
        old_access_token = self._access_token
        old_refresh_token = self._refresh_token
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
            need_auth=False,
        )
        self._last_refresh_result = result if isinstance(result, dict) else {"result": result}
        if result.get("access_token"):
            self._access_token = result.get("access_token") or ""
            self._refresh_token = result.get("refresh_token") or self._refresh_token
            self._last_refresh_invalid = False
            logger.info("【光鸭云盘助手】Token 刷新成功")
            if self._on_token_refresh:
                try:
                    self._on_token_refresh(self._access_token, self._refresh_token)
                except Exception as err:
                    logger.error("【光鸭云盘助手】Token 刷新回调失败: %s", err)
            return True
        self._last_refresh_invalid = self._is_auth_invalid_result(result)
        logger.warning(
            "【光鸭云盘助手】Token 刷新失败: device_id=%s, auth_invalid=%s, response=%s",
            self._device_id, self._last_refresh_invalid, result,
        )
        return False

    def get_user_info(self) -> Dict[str, Any]:
        return self._request("GET", f"{self.ACCOUNT_BASE_URL}/v1/user/me")

    def get_assets(self) -> Dict[str, Any]:
        return self._request("POST", f"{self.API_BASE_URL}/nd.bizassets.s/v1/get_assets", data={})

    def get_file_list(
        self,
        parent_id: str = "",
        page_size: int = 100,
        order_by: int = 3,
        sort_type: int = 1,
        file_types: list = None,
        page: int = 0,
        dir_type: int = None,
    ) -> Dict[str, Any]:
        data = {
            "parentId": parent_id or "",
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "sortType": sort_type,
            "fileTypes": file_types or [],
        }
        if dir_type is not None:
            data["dirType"] = dir_type
        return self._request(
            method="POST",
            url=f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/get_file_list",
            data=data,
        )

    def create_dir(self, parent_id: str, dir_name: str, fail_if_exist: bool = True) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/create_dir",
            data={"parentId": parent_id or "", "dirName": dir_name, "failIfNameExist": fail_if_exist},
        )

    def rename(self, file_id: str, new_name: str) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/rename",
            data={"fileId": file_id, "newName": new_name},
        )

    def delete_file(self, file_ids: list) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/delete_file",
            data={"fileIds": file_ids},
        )

    def move_file(self, file_ids: list, target_parent_id: str) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/move_file",
            data={"fileIds": file_ids, "parentId": target_parent_id},
        )

    def copy_file(self, file_ids: list, target_parent_id: str) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/copy_file",
            data={"fileIds": file_ids, "parentId": target_parent_id},
        )

    def get_download_url(self, file_id: str) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/get_res_download_url",
            data={"fileId": file_id},
        )

    def get_upload_token(
        self,
        file_name: str,
        file_size: int,
        file_md5: str,
        parent_id: str = "",
        capacity: int = 1,
    ) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/get_res_center_token",
            data={
                "capacity": capacity,
                "name": file_name,
                "res": {"fileSize": file_size, "md5": file_md5},
                "parentId": parent_id or "",
            },
        )

    def check_flash_upload(
        self,
        task_id: str,
        gcid: str,
        file_size: int = None,
        file_name: str = None,
        parent_id: str = None,
    ) -> Dict[str, Any]:
        data = {"taskId": task_id, "gcid": gcid}
        if file_size is not None:
            data["fileSize"] = file_size
        if file_name:
            data["name"] = file_name
        if parent_id is not None:
            data["parentId"] = parent_id
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/check_can_flash_upload", data=data,
        )

    def get_resume_token(self, task_id: str, file_size: int) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/get_res_center_resume_token",
            data={"capacity": 2, "res": {"fileSize": file_size}, "taskId": task_id},
        )

    def get_file_info_by_task_id(self, task_id: str) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/file/get_info_by_task_id",
            data={"taskId": task_id},
        )

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        return self._request(
            "POST", f"{self.API_BASE_URL}/nd.bizuserres.s/v1/get_task_status",
            data={"taskId": task_id},
        )

    def upload_file_multipart(
        self,
        endpoint: str,
        bucket_name: str,
        object_path: str,
        file_path: str,
        oss_access_key_id: str,
        oss_access_key_secret: str,
        security_token: str,
        progress_callback: Callable = None,
    ) -> Optional[str]:
        """使用 MoviePilot 已有 requests 直接执行 OSS STS 分片上传。"""
        try:
            return _native_oss_multipart_upload(
                endpoint=endpoint,
                bucket_name=bucket_name,
                object_path=object_path,
                file_path=file_path,
                oss_access_key_id=oss_access_key_id,
                oss_access_key_secret=oss_access_key_secret,
                security_token=security_token,
                progress_callback=progress_callback,
            )
        except Exception as err:
            logger.error("【光鸭云盘助手】OSS 原生分片上传失败: %s", err)
            return None

# =============================================================================
# GuangYa HTTP client V3 facade
# =============================================================================

"""光鸭云盘 HTTP 客户端兼容层。

文件 API 继续复用原实现；扫码登录严格沿用 KoWming 当前可用实现，
短信登录参考 DDSRem-Dev/guangyaclient 当前实现。
"""

import time
from secrets import token_hex
from typing import Any, Dict, Optional

from app.sdk.logging import logger

class GuangYaClient(_LegacyGuangYaClient):
    """在原客户端之上补充当前认证流程与临时网络故障重试。"""

    _TRANSIENT_NETWORK_MARKERS = (
        "NameResolutionError",
        "Temporary failure in name resolution",
        "Failed to resolve",
        "ConnectionError",
        "Connection aborted",
        "Connection reset",
        "Read timed out",
        "ConnectTimeout",
        "ReadTimeout",
        "Max retries exceeded",
    )

    @classmethod
    def _is_transient_network_result(cls, result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("code") not in (-1, None) and not result.get("error"):
            return False
        text = str(result.get("error") or result.get("msg") or result)
        return any(marker.lower() in text.lower() for marker in cls._TRANSIENT_NETWORK_MARKERS)

    def _request(self, *args, **kwargs) -> Dict[str, Any]:
        """对 legacy HTTP 请求增加临时 DNS/连接故障重试。"""
        max_attempts = 3
        last_result: Dict[str, Any] = {}
        url = kwargs.get("url") or (args[1] if len(args) > 1 else "")
        for attempt in range(1, max_attempts + 1):
            last_result = super()._request(*args, **kwargs)
            if not self._is_transient_network_result(last_result):
                return last_result
            if attempt >= max_attempts:
                break
            delay = 2 ** (attempt - 1)
            logger.warning(
                "【光鸭云盘助手】【网络】临时网络/DNS异常，第 %s/%s 次请求失败，%ss 后重试: %s",
                attempt,
                max_attempts,
                delay,
                url,
            )
            time.sleep(delay)
        return last_result

    def upload_file_multipart(
        self,
        endpoint: str,
        bucket_name: str,
        object_path: str,
        file_path: str,
        oss_access_key_id: str,
        oss_access_key_secret: str,
        security_token: str,
        progress_callback=None,
    ):
        """对 OSS 可续传上传增加临时 DNS/连接故障重试。"""
        max_attempts = 5
        last_result = None
        for attempt in range(1, max_attempts + 1):
            try:
                last_result = super().upload_file_multipart(
                    endpoint=endpoint,
                    bucket_name=bucket_name,
                    object_path=object_path,
                    file_path=file_path,
                    oss_access_key_id=oss_access_key_id,
                    oss_access_key_secret=oss_access_key_secret,
                    security_token=security_token,
                    progress_callback=progress_callback,
                )
                if last_result:
                    if attempt > 1:
                        logger.info(
                            "【光鸭云盘助手】【上传】OSS 重试成功，第 %s 次完成: %s",
                            attempt,
                            object_path,
                        )
                    return last_result
            except Exception as err:
                logger.warning(
                    "【光鸭云盘助手】【上传】OSS 上传异常，第 %s/%s 次: %s",
                    attempt,
                    max_attempts,
                    err,
                )
            if attempt < max_attempts:
                delay = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "【光鸭云盘助手】【上传】OSS 上传未完成，%ss 后重试，第 %s/%s 次",
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)
        logger.error(
            "【光鸭云盘助手】【上传】OSS 重试 %s 次仍失败: %s",
            max_attempts,
            object_path,
        )
        return last_result

    def _account_web_headers(self) -> Dict[str, str]:
        return {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": "https://www.guangyapan.com",
            "Referer": "https://www.guangyapan.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36"
            ),
            "X-Client-Id": self._client_id,
            "X-Client-Version": "0.0.1",
            "X-Device-Id": self._device_id,
            "X-Device-Model": "chrome%2F147.0.0.0",
            "X-Device-Name": "PC-Chrome",
            "X-Device-Sign": f"wdi10.{self._device_id}{token_hex(16)}",
            "X-Net-Work-Type": "NONE",
            "X-OS-Version": "MacIntel",
            "X-Platform-Version": "1",
            "X-Protocol-Version": "301",
            "X-Provider-Name": "NONE",
            "X-SDK-Version": "9.0.2",
        }

    @staticmethod
    def _auth_error_message(result: Any) -> str:
        if not isinstance(result, dict):
            return str(result or "未知错误")
        return str(
            result.get("error_description")
            or result.get("message")
            or result.get("msg")
            or result.get("error")
            or result
        )

    def get_device_code(self) -> Optional[Dict[str, Any]]:
        """获取设备码；保留上游错误，并在普通请求失败时用网页认证头重试一次。"""
        payload = {"scope": "user", "client_id": self._client_id}
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/device/code",
            data=payload,
            need_auth=False,
            treat_http_error_as_response=True,
        ) or {}
        if result.get("error") or not result.get("device_code"):
            retry = self._request(
                method="POST",
                url=f"{self.ACCOUNT_BASE_URL}/v1/auth/device/code",
                data=payload,
                headers=self._account_web_headers(),
                need_auth=False,
                treat_http_error_as_response=True,
            ) or {}
            if retry.get("device_code"):
                result = retry
            elif retry:
                # 返回信息更完整的一次，绝不再把上游失败吞成 None。
                result = retry
        return result

    def poll_device_code(self, device_code: str) -> Optional[Dict[str, Any]]:
        """轮询设备码状态；authorization_pending 以外的错误也原样投影给插件层。"""
        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": self._client_id,
        }
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/token",
            data=payload,
            need_auth=False,
            treat_http_error_as_response=True,
        ) or {}
        if result.get("error") and result.get("error") != "authorization_pending":
            retry = self._request(
                method="POST",
                url=f"{self.ACCOUNT_BASE_URL}/v1/auth/token",
                data=payload,
                headers=self._account_web_headers(),
                need_auth=False,
                treat_http_error_as_response=True,
            ) or {}
            if retry.get("access_token") or retry.get("error") == "authorization_pending":
                result = retry
            elif retry:
                result = retry

        error = str(result.get("error") or "")
        if error == "authorization_pending":
            return {"waiting": True, "stage": "authorization_pending", "message": "等待扫码中..."}
        if result.get("access_token"):
            self._access_token = result.get("access_token") or ""
            self._refresh_token = result.get("refresh_token") or ""
            if self._on_token_refresh:
                try:
                    self._on_token_refresh(self._access_token, self._refresh_token)
                except Exception:
                    pass
            return result
        if result:
            return {
                **result,
                "waiting": False,
                "stage": "device_token_error",
                "message": self._auth_error_message(result),
            }
        return {"waiting": False, "stage": "device_token_empty", "message": "光鸭登录接口未返回有效响应"}

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        value = str(phone or "").strip()
        if not value:
            return ""
        compact = value.replace(" ", "")
        if compact.startswith("+86"):
            return "+86 " + compact[3:]
        digits = "".join(ch for ch in compact if ch.isdigit())
        if len(digits) == 11:
            return "+86 " + digits
        return value

    def login_sms_init(self, phone_number: str, captcha_token: Optional[str] = None) -> Dict[str, Any]:
        phone = self._normalize_phone(phone_number)
        body: Dict[str, Any] = {
            "client_id": self._client_id,
            "action": "POST:/v1/auth/verification",
            "device_id": self._device_id,
            "meta": {"phone_number": phone},
        }
        if captcha_token:
            body["captcha_token"] = captcha_token
        return self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/shield/captcha/init",
            data=body,
            headers=self._account_web_headers(),
            need_auth=False,
            treat_http_error_as_response=True,
        ) or {}

    def login_sms_send(self, phone_number: str, captcha_token: str, target: str = "ANY") -> Dict[str, Any]:
        phone = self._normalize_phone(phone_number)
        headers = self._account_web_headers()
        headers["X-Captcha-Token"] = captcha_token
        return self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/verification",
            data={
                "phone_number": phone,
                "target": target,
                "client_id": self._client_id,
            },
            headers=headers,
            need_auth=False,
            treat_http_error_as_response=True,
        ) or {}

    def login_sms_verify(self, verification_id: str, verification_code: str) -> Dict[str, Any]:
        return self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/verification/verify",
            data={
                "verification_id": str(verification_id or "").strip(),
                "verification_code": str(verification_code or "").strip(),
                "client_id": self._client_id,
            },
            headers=self._account_web_headers(),
            need_auth=False,
            treat_http_error_as_response=True,
        ) or {}

    def login_sms_signin(
        self,
        verification_code: str,
        verification_token: str,
        username: str,
        captcha_token: str,
    ) -> Dict[str, Any]:
        phone = self._normalize_phone(username)
        headers = self._account_web_headers()
        headers["X-Captcha-Token"] = captcha_token
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/signin",
            data={
                "verification_code": str(verification_code or "").strip(),
                "verification_token": str(verification_token or "").strip(),
                "username": phone,
                "client_id": self._client_id,
            },
            headers=headers,
            need_auth=False,
            treat_http_error_as_response=True,
        ) or {}
        access_token = str(result.get("access_token") or "").strip()
        if access_token:
            self._access_token = access_token
            self._refresh_token = str(result.get("refresh_token") or "").strip()
            if self._on_token_refresh:
                try:
                    self._on_token_refresh(self._access_token, self._refresh_token)
                except Exception:
                    pass
        return result

    def request_sms_code(self, phone_number: str, captcha_token: str = "") -> Dict[str, Any]:
        phone = self._normalize_phone(phone_number)
        captcha = str(captcha_token or "").strip()
        if not captcha:
            init_result = self.login_sms_init(phone)
            captcha = str(
                init_result.get("captcha_token")
                or init_result.get("captchaToken")
                or (init_result.get("data") or {}).get("captcha_token")
                or ""
            ).strip()
            if not captcha:
                return {
                    "success": False,
                    "stage": "captcha_init",
                    "upstream": f"{self.ACCOUNT_BASE_URL}/v1/shield/captcha/init",
                    "error": init_result.get("error") or "captcha_init_failed",
                    "message": init_result.get("error_description")
                    or init_result.get("msg")
                    or init_result.get("error")
                    or "无法获取 captcha token",
                    "raw": init_result,
                }

        send_result = self.login_sms_send(phone, captcha)
        verification_id = str(
            send_result.get("verification_id")
            or send_result.get("verificationId")
            or (send_result.get("data") or {}).get("verification_id")
            or ""
        ).strip()
        if not verification_id:
            return {
                "success": False,
                "stage": "verification_send",
                "upstream": f"{self.ACCOUNT_BASE_URL}/v1/auth/verification",
                "error": send_result.get("error") or "verification_failed",
                "message": send_result.get("error_description")
                or send_result.get("msg")
                or send_result.get("error")
                or "发送验证码失败",
                "captcha_token": captcha,
                "raw": send_result,
            }
        return {
            "success": True,
            "verification_id": verification_id,
            "captcha_token": captcha,
            "phone_number": phone,
        }

    def signin_by_sms(
        self,
        phone_number: str,
        verification_id: str,
        verification_code: str,
        captcha_token: str,
    ) -> Dict[str, Any]:
        phone = self._normalize_phone(phone_number)
        code = str(verification_code or "").strip()
        verify_result = self.login_sms_verify(verification_id, code)
        verification_token = str(
            verify_result.get("verification_token")
            or verify_result.get("verificationToken")
            or (verify_result.get("data") or {}).get("verification_token")
            or ""
        ).strip()
        if not verification_token:
            return {
                "success": False,
                "stage": "verification_verify",
                "upstream": f"{self.ACCOUNT_BASE_URL}/v1/auth/verification/verify",
                "error": verify_result.get("error") or "verify_code_failed",
                "message": verify_result.get("error_description")
                or verify_result.get("msg")
                or verify_result.get("error")
                or "验证码校验失败",
                "raw": verify_result,
            }

        result = self.login_sms_signin(
            verification_code=code,
            verification_token=verification_token,
            username=phone,
            captcha_token=captcha_token,
        )
        access_token = str(result.get("access_token") or "").strip()
        if not access_token:
            return {
                "success": False,
                "stage": "signin",
                "upstream": f"{self.ACCOUNT_BASE_URL}/v1/auth/signin",
                "error": result.get("error") or "signin_failed",
                "message": result.get("error_description")
                or result.get("msg")
                or result.get("error")
                or "登录失败",
                "raw": result,
            }

        return {
            "success": True,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_in": result.get("expires_in"),
        }


__all__ = ["GuangYaClient"]

# =============================================================================
# GuangYa storage API legacy core
# =============================================================================

"""
光鸭云盘基础操作类
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from hashlib import md5
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from app import schemas
from app.sdk.config import global_vars, settings
from app.sdk.logging import logger
from app.modules.filemanager.storages import transfer_process

class _LegacyGuangYaApi:
    """
    光鸭云盘基础操作类。
    """

    _id_cache: Dict[str, str] = {}
    _item_cache: Dict[str, dict] = {}

    def __init__(
        self,
        client: GuangYaClient,
        disk_name: str,
        page_size: int = 100,
        order_by: int = 3,
        sort_type: int = 1,
        permanently_delete: bool = False,
    ):
        """
        初始化 API。
        """
        self.client = client
        self._disk_name = disk_name
        self._page_size = page_size or 100
        self._order_by = order_by
        self._sort_type = sort_type
        self._permanently_delete = permanently_delete
        self._pending_purge_keys = set()
        self._pending_purge_lock = threading.Lock()
        self.transtype = {"move": "移动", "copy": "复制"}

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = str(path or "/").replace("\\", "/")
        if normalized in ("", "."):
            return "/"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        normalized = normalized.rstrip("/") or "/"
        return normalized

    def _build_path(self, parent_path: str, name: str, is_dir: bool) -> str:
        normalized_parent = self._normalize_path(parent_path)
        item_path = f"{normalized_parent.rstrip('/')}/{name}" if normalized_parent != "/" else f"/{name}"
        return item_path + ("/" if is_dir else "")

    @staticmethod
    def _normalize_fileid(fileid: Optional[str], path: Optional[str] = None) -> str:
        normalized_fileid = str(fileid or "")
        normalized_path = str(path or "").replace("\\", "/")
        if normalized_fileid == "root" and normalized_path in ("", "/"):
            return ""
        return normalized_fileid

    def _cache_item(self, item: schemas.FileItem) -> None:
        normalized_path = self._normalize_path(item.path)
        normalized_fileid = self._normalize_fileid(item.fileid, normalized_path)
        if normalized_path != "/" and normalized_fileid:
            self._id_cache[normalized_path] = normalized_fileid
        self._item_cache[normalized_path] = {
            "storage": item.storage,
            "fileid": normalized_fileid,
            "parent_fileid": str(item.parent_fileid or ""),
            "name": item.name,
            "basename": item.basename,
            "extension": item.extension,
            "type": item.type,
            "path": item.path,
            "size": item.size,
            "modify_time": item.modify_time,
            "pickcode": item.pickcode,
        }

    def _invalidate_path_cache(self, path: str) -> None:
        normalized_path = self._normalize_path(path)
        self._id_cache.pop(normalized_path, None)
        self._item_cache.pop(normalized_path, None)
        dir_key = normalized_path if normalized_path == "/" else f"{normalized_path.rstrip('/')}/"
        file_key = normalized_path.rstrip("/") or "/"
        self._id_cache.pop(dir_key, None)
        self._item_cache.pop(dir_key, None)
        self._id_cache.pop(file_key, None)
        self._item_cache.pop(file_key, None)

    def _cache_path_id(self, path: str, file_id: str) -> None:
        normalized_path = self._normalize_path(path)
        normalized_fileid = self._normalize_fileid(file_id, normalized_path)
        if normalized_path != "/" and normalized_fileid:
            self._id_cache[normalized_path] = normalized_fileid

    def _iter_parent_items(self, parent_id: str, parent_path: str) -> List[schemas.FileItem]:
        results: List[schemas.FileItem] = []
        page = 0
        while True:
            response = self.client.get_file_list(
                parent_id=parent_id,
                page_size=self._page_size,
                order_by=self._order_by,
                sort_type=self._sort_type,
                file_types=[],
                page=page,
            )
            if response.get("code", -1) != 0 and response.get("msg") != "success":
                break
            data = response.get("data", {}) or {}
            item_list = data.get("list", []) or []
            if not item_list:
                break
            for item in item_list:
                results.append(self._build_file_item_from_api(parent_path, item))
            total = data.get("total") or 0
            if len(item_list) < self._page_size or (total and len(results) >= total):
                break
            page += 1
        return results

    def _iter_recycle_items(self) -> List[schemas.FileItem]:
        results: List[schemas.FileItem] = []
        page = 1
        while True:
            response = self.client.get_file_list(
                parent_id="",
                page_size=self._page_size,
                order_by=10,
                sort_type=0,
                file_types=[],
                page=page,
                dir_type=4,
            )
            if response.get("code", -1) != 0 and response.get("msg") != "success":
                break
            data = response.get("data", {}) or {}
            item_list = data.get("list", []) or []
            if not item_list:
                break
            for item in item_list:
                recycle_item = self._build_file_item_from_api("/", item)
                recycle_item.path = self._build_path("/.recycle_bin", recycle_item.name, recycle_item.type == "dir")
                results.append(recycle_item)
            total = data.get("total") or 0
            if len(item_list) < self._page_size or (total and len(results) >= total):
                break
            page += 1
        return results

    def _match_recycle_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        target_fileid = str(fileitem.fileid or "")
        target_name = str(fileitem.name or "")
        target_size = fileitem.size
        candidates = self._iter_recycle_items()

        for item in candidates:
            if target_fileid and str(item.fileid or "") == target_fileid:
                return item

        same_name_items = [item for item in candidates if item.name == target_name]
        if len(same_name_items) == 1:
            return same_name_items[0]

        if target_size is not None:
            sized_items = [item for item in same_name_items if item.size == target_size]
            if len(sized_items) == 1:
                return sized_items[0]

        return None

    def _purge_from_recycle(self, fileitem: schemas.FileItem, max_try: int = 8, interval: float = 1.0) -> bool:
        recycle_item = None
        for index in range(max_try):
            recycle_item = self._match_recycle_item(fileitem)
            if recycle_item:
                break
            if index < max_try - 1:
                time.sleep(interval)

        if not recycle_item:
            logger.warning(f"【光鸭云盘助手】未在回收站中定位到待彻底删除项目: {fileitem.name}")
            return False

        response = self.client.delete_file([recycle_item.fileid])
        if response.get("msg") != "success" and response.get("code") != 0:
            logger.warning(f"【光鸭云盘助手】回收站彻底删除失败: {response}")
            return False

        task_id = (response.get("data", {}) or {}).get("taskId", "")
        if task_id and not self._wait_task_done(task_id, allow_missing=True):
            return False
        return True

    @staticmethod
    def _clone_fileitem(fileitem: schemas.FileItem) -> schemas.FileItem:
        return schemas.FileItem(
            storage=fileitem.storage,
            fileid=str(fileitem.fileid or ""),
            parent_fileid=str(fileitem.parent_fileid or ""),
            name=fileitem.name,
            basename=fileitem.basename,
            extension=fileitem.extension,
            type=fileitem.type,
            path=fileitem.path,
            size=fileitem.size,
            modify_time=fileitem.modify_time,
            pickcode=fileitem.pickcode,
        )

    def _build_purge_key(self, fileitem: schemas.FileItem) -> str:
        return str(fileitem.fileid or "") or self._normalize_path(fileitem.path or fileitem.name or "")

    def _schedule_purge_from_recycle(
        self,
        fileitem: schemas.FileItem,
        initial_delay: float = 15.0,
        max_try: int = 90,
        interval: float = 2.0,
    ) -> None:
        purge_item = self._clone_fileitem(fileitem)
        purge_key = self._build_purge_key(purge_item)

        with self._pending_purge_lock:
            if purge_key in self._pending_purge_keys:
                logger.info(f"【光鸭云盘助手】彻底删除任务已在队列中: {purge_item.name}")
                return
            self._pending_purge_keys.add(purge_key)

        def _worker() -> None:
            try:
                logger.info(f"【光鸭云盘助手】已加入延迟彻底删除队列，等待刮削及空目录清理完成: {purge_item.name}")
                if initial_delay > 0:
                    time.sleep(initial_delay)
                if self._purge_from_recycle(purge_item, max_try=max_try, interval=interval):
                    logger.info(f"【光鸭云盘助手】延迟彻底删除成功: {purge_item.name}")
                else:
                    logger.warning(f"【光鸭云盘助手】延迟彻底删除失败，回收站中仍未找到目标: {purge_item.name}")
            except Exception as err:
                logger.warning(f"【光鸭云盘助手】延迟彻底删除异常: {purge_item.name} - {err}")
            finally:
                with self._pending_purge_lock:
                    self._pending_purge_keys.discard(purge_key)

        threading.Thread(target=_worker, name=f"guangya-purge-{int(time.time())}", daemon=True).start()

    def _find_item_in_parent(
        self,
        parent_path: str,
        name: str,
        expected_type: Optional[str] = None,
    ) -> Optional[schemas.FileItem]:
        normalized_parent_path = self._normalize_path(parent_path)
        parent_id = ""
        if normalized_parent_path != "/":
            try:
                parent_id = self._path_to_id(normalized_parent_path)
            except FileNotFoundError:
                return None

        for item in self._iter_parent_items(parent_id=parent_id, parent_path=normalized_parent_path):
            if item.name != name:
                continue
            if expected_type and item.type != expected_type:
                continue
            return item
        return None

    def _wait_item_visible(
        self,
        parent_path: str,
        name: str,
        expected_type: Optional[str] = None,
        max_try: int = 10,
        interval: float = 0.3,
    ) -> Optional[schemas.FileItem]:
        for index in range(max_try):
            item = self._find_item_in_parent(parent_path=parent_path, name=name, expected_type=expected_type)
            if item:
                return item
            if index < max_try - 1:
                time.sleep(interval)
        return None

    @staticmethod
    def _is_task_missing(response: Optional[dict]) -> bool:
        payload = response or {}
        code = payload.get("code")
        message = str(payload.get("msg") or payload.get("error") or "")
        return code in (145, 147) or "任务不存在" in message

    def _restore_cached_item(self, path: str) -> Optional[schemas.FileItem]:
        cached = self._item_cache.get(self._normalize_path(path))
        if not cached:
            return None
        return schemas.FileItem(**cached)

    def _build_file_item_from_api(self, parent_path: str, item: dict) -> schemas.FileItem:
        file_name = item.get("fileName", "")
        item_id = str(item.get("fileId", ""))
        is_dir = item.get("resType") == 2
        file_path = self._build_path(parent_path, file_name, is_dir)
        file_item = schemas.FileItem(
            storage=self._disk_name,
            fileid=item_id,
            parent_fileid=str(item.get("parentId", "") or ""),
            name=file_name,
            basename=file_name if is_dir else Path(file_name).stem,
            extension=None if is_dir or not Path(file_name).suffix else Path(file_name).suffix[1:],
            type="dir" if is_dir else "file",
            path=file_path,
            size=item.get("fileSize") if not is_dir else None,
            modify_time=int(item.get("utime") or item.get("updateTime") or 0) or None,
            pickcode=str(item),
        )
        self._cache_item(file_item)
        return file_item

    def _wait_task_done(
        self,
        task_id: str,
        max_try: int = 300,
        interval: int = 1,
        allow_missing: bool = False,
    ) -> bool:
        """
        等待任务完成。
        """
        if not task_id:
            return True

        for index in range(max_try):
            status_response = self.client.get_task_status(task_id)
            status_code = status_response.get("code", -1)
            status_data = status_response.get("data", {}) or {}
            status = status_data.get("status")
            if status == 2:
                return True

            if status in (0, 1, 3, 145, 146, 147, 155, 163) and index < max_try - 1:
                time.sleep(interval)
                continue

            info_response = self.client.get_file_info_by_task_id(task_id)
            info_code = info_response.get("code", -1)
            info_data = info_response.get("data", {}) or {}
            if info_data.get("fileId"):
                return True

            if allow_missing and (self._is_task_missing(status_response) or self._is_task_missing(info_response)):
                logger.info(f"【光鸭云盘助手】任务 {task_id} 状态已失效，转由后续文件可见性确认结果")
                return True

            message = status_response.get("msg") or info_response.get("msg") or ""
            logger.warning(
                f"【光鸭云盘助手】任务 {task_id} 未确认完成: status={status} code={status_code}/{info_code} msg={message}"
            )
            return False

        logger.error(f"【光鸭云盘助手】任务 {task_id} 超时")
        return False

    def _path_to_id(self, path: str) -> str:
        """
        通过路径获取文件 ID。
        """
        normalized_path = self._normalize_path(path)
        if normalized_path == "/":
            return ""
        if normalized_path in self._id_cache:
            return self._id_cache[normalized_path]

        current_id = ""
        current_path = "/"
        parts = Path(normalized_path).parts[1:]
        for part in parts:
            response = self.client.get_file_list(
                parent_id=current_id,
                page_size=self._page_size,
                order_by=self._order_by,
                sort_type=self._sort_type,
                file_types=[],
            )
            if response.get("code", -1) != 0 and response.get("msg") != "success":
                raise FileNotFoundError(f"【光鸭云盘助手】{normalized_path} 不存在")
            data = response.get("data", {}) or {}
            items = data.get("list", []) or []
            found = None
            for item in items:
                if item.get("fileName") == part:
                    found = item
                    break
            if not found:
                raise FileNotFoundError(f"【光鸭云盘助手】{normalized_path} 不存在")
            current_id = str(found.get("fileId", ""))
            current_path = f"{current_path.rstrip('/')}/{part}" if current_path != "/" else f"/{part}"
            self._cache_path_id(current_path, current_id)
            self._build_file_item_from_api(str(Path(current_path).parent).replace("\\", "/") or "/", found)

        return current_id

    def list(self, fileitem: schemas.FileItem) -> List[schemas.FileItem]:
        """
        浏览文件或目录。
        """
        if fileitem.type == "file":
            item = self.detail(fileitem)
            return [item] if item else []

        normalized_dir_path = self._normalize_path(fileitem.path)
        file_id = self._normalize_fileid(fileitem.fileid, normalized_dir_path)
        if normalized_dir_path != "/" and not file_id:
            file_id = self._path_to_id(normalized_dir_path)

        dir_item = schemas.FileItem(
            storage=self._disk_name,
            fileid=file_id,
            parent_fileid=str(fileitem.parent_fileid or ""),
            path="/" if normalized_dir_path == "/" else f"{normalized_dir_path}/",
            name=fileitem.name or ("/" if normalized_dir_path == "/" else Path(normalized_dir_path).name),
            basename=fileitem.basename or ("/" if normalized_dir_path == "/" else Path(normalized_dir_path).name),
            type="dir",
        )
        self._cache_item(dir_item)

        results: List[schemas.FileItem] = []
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
            if response.get("code", -1) != 0 and response.get("msg") != "success":
                break
            data = response.get("data", {}) or {}
            item_list = data.get("list", []) or []
            if not item_list:
                break
            for item in item_list:
                results.append(self._build_file_item_from_api(normalized_dir_path, item))
            total = data.get("total") or 0
            if len(item_list) < self._page_size or (total and len(results) >= total):
                break
            page += 1
        return results

    def create_folder(self, fileitem: schemas.FileItem, name: str) -> Optional[schemas.FileItem]:
        """
        创建目录。
        """
        try:
            normalized_parent_path = self._normalize_path(fileitem.path)
            parent_id = self._normalize_fileid(fileitem.fileid, normalized_parent_path)
            if normalized_parent_path != "/" and not parent_id:
                parent_id = self._path_to_id(normalized_parent_path)
            response = self.client.create_dir(parent_id=parent_id, dir_name=name)
            if response.get("msg") != "success" and response.get("code") != 0:
                logger.debug(f"【光鸭云盘助手】创建目录失败: {response}")
                return None
            data = response.get("data", {}) or {}
            new_path = self._normalize_path(str(Path(normalized_parent_path) / name))
            self._id_cache[new_path] = str(data.get("fileId", ""))
            folder_item = schemas.FileItem(
                storage=self._disk_name,
                fileid=str(data.get("fileId", "")),
                parent_fileid=str(parent_id or ""),
                path=new_path + "/",
                name=name,
                basename=name,
                type="dir",
                modify_time=int(datetime.now().timestamp()),
                pickcode=str(data),
            )
            self._cache_item(folder_item)
            return folder_item
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】创建目录失败: {err}")
            return None

    def get_folder(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取目录，不存在则创建。
        """
        folder = self.get_item(path)
        if folder:
            return folder

        current = schemas.FileItem(storage=self._disk_name, path="/", fileid="")
        for part in path.parts[1:]:
            next_folder = None
            for sub_folder in self.list(current):
                if sub_folder.type == "dir" and sub_folder.name == part:
                    next_folder = sub_folder
                    break
            if not next_folder:
                next_folder = self.create_folder(current, part)
            if not next_folder:
                return None
            current = next_folder
        return current

    def get_item(self, path: Path) -> Optional[schemas.FileItem]:
        """
        查询文件或目录。
        """
        normalized = self._normalize_path(str(path))
        if normalized == "/":
            root_item = schemas.FileItem(
                storage=self._disk_name,
                fileid="",
                parent_fileid="",
                path="/",
                name="/",
                basename="/",
                type="dir",
            )
            self._cache_item(root_item)
            return root_item

        cached_item = self._restore_cached_item(normalized)
        if cached_item:
            return cached_item

        try:
            file_id = self._path_to_id(normalized)
        except FileNotFoundError:
            return None

        parent_path = self._normalize_path(str(Path(normalized).parent))
        target_name = Path(normalized).name
        item = self._find_item_in_parent(parent_path=parent_path, name=target_name)
        if item and str(item.fileid or "") == file_id:
            return item
        return None

    def get_parent(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取父目录。
        """
        current_path = (fileitem.path or "/").replace("\\", "/")
        normalized_path = self._normalize_path(current_path)
        if normalized_path == "/":
            return self.get_item(Path("/"))

        parent_path = self._normalize_path(str(Path(normalized_path).parent))

        cached_parent = self._restore_cached_item(parent_path)
        if cached_parent and cached_parent.type == "dir":
            return cached_parent

        parent_fileid = str(fileitem.parent_fileid or "")
        grand_parent_fileid = ""
        if parent_path != "/":
            try:
                parent_item = self.get_item(Path(parent_path))
                if parent_item:
                    grand_parent_fileid = str(parent_item.parent_fileid or "")
                    if not parent_fileid:
                        parent_fileid = str(parent_item.fileid or "")
            except Exception:
                pass

        parent_item = schemas.FileItem(
            storage=self._disk_name,
            fileid=parent_fileid,
            parent_fileid=grand_parent_fileid,
            path=parent_path if parent_path == "/" else f"{parent_path.rstrip('/')}/",
            name="/" if parent_path == "/" else Path(parent_path).name,
            basename="/" if parent_path == "/" else Path(parent_path).name,
            type="dir",
        )
        self._cache_item(parent_item)
        return parent_item

    def delete(self, fileitem: schemas.FileItem) -> bool:
        """
        删除文件或目录。
        """
        try:
            response = self.client.delete_file([fileitem.fileid])
            if response.get("msg") != "success" and response.get("code") != 0:
                return False
            task_id = (response.get("data", {}) or {}).get("taskId", "")
            if task_id and not self._wait_task_done(task_id, allow_missing=True):
                return False
            if self._permanently_delete:
                self._schedule_purge_from_recycle(fileitem)
            self._invalidate_path_cache(fileitem.path)
            return True
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】删除异常: {err}")
            return False

    def rename(self, fileitem: schemas.FileItem, name: str) -> bool:
        """
        重命名文件或目录。
        """
        try:
            response = self.client.rename(file_id=fileitem.fileid, new_name=name)
            if response.get("msg") != "success" and response.get("code") != 0:
                return False
            self._invalidate_path_cache(fileitem.path)
            new_path = self._normalize_path(str(Path(fileitem.path).parent / name))
            renamed_item = schemas.FileItem(
                storage=self._disk_name,
                fileid=str(fileitem.fileid or ""),
                parent_fileid=str(fileitem.parent_fileid or ""),
                path=new_path + ("/" if fileitem.type == "dir" else ""),
                name=name,
                basename=name if fileitem.type == "dir" else Path(name).stem,
                extension=None if fileitem.type == "dir" or not Path(name).suffix else Path(name).suffix[1:],
                type=fileitem.type,
                size=fileitem.size,
                modify_time=int(datetime.now().timestamp()),
                pickcode=fileitem.pickcode,
            )
            self._cache_item(renamed_item)
            return True
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】重命名异常: {err}")
            return False

    def download(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
        """
        下载文件。
        """
        try:
            response = self.client.get_download_url(fileitem.fileid)
            if response.get("msg") != "success" and response.get("code") != 0:
                return None
            data = response.get("data", {}) or {}
            download_url = data.get("signedURL") or data.get("downloadUrl")
            if not download_url:
                return None
            local_path = (path or settings.TEMP_PATH) / fileitem.name
            file_size = fileitem.size
            progress_callback = transfer_process(Path(fileitem.path).as_posix())
            with requests.get(download_url, stream=True, timeout=300) as response_obj:
                response_obj.raise_for_status()
                downloaded_size = 0
                with open(local_path, "wb") as file_obj:
                    for chunk in response_obj.iter_content(chunk_size=10 * 1024 * 1024):
                        if global_vars.is_transfer_stopped(fileitem.path):
                            return None
                        if not chunk:
                            continue
                        file_obj.write(chunk)
                        downloaded_size += len(chunk)
                        if file_size:
                            progress_callback((downloaded_size * 100) / file_size)
            progress_callback(100)
            return local_path
        except Exception as err:
            logger.error(f"【光鸭云盘助手】下载失败: {fileitem.name} - {err}")
            try:
                if 'local_path' in locals() and local_path.exists():
                    local_path.unlink()
            except Exception:
                pass
            return None

    def upload(
        self,
        target_dir: schemas.FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[schemas.FileItem]:
        """
        上传文件或目录。
        """
        if local_path.is_dir():
            return self.upload_folder(target_dir, local_path)
        return self._upload_single_file_public(target_dir, local_path, new_name)

    def upload_batch(
        self,
        target_dir: schemas.FileItem,
        local_paths: List[Path],
    ) -> List[Optional[schemas.FileItem]]:
        """
        并行上传多个文件。
        """
        if not local_paths:
            return []
        if len(local_paths) == 1:
            return [self._upload_single_file_public(target_dir, local_paths[0])]

        results: List[Optional[schemas.FileItem]] = [None] * len(local_paths)

        def _upload_one(index: int, upload_path: Path):
            return index, self._upload_single_file_public(target_dir, upload_path)

        with ThreadPoolExecutor(max_workers=min(5, len(local_paths))) as executor:
            futures = [executor.submit(_upload_one, index, upload_path) for index, upload_path in enumerate(local_paths)]
            for future in as_completed(futures):
                try:
                    index, result = future.result()
                    results[index] = result
                except Exception as err:
                    logger.error(f"【光鸭云盘助手】并行上传异常: {err}")
        return results

    def _upload_single_file_public(
        self,
        target_dir: schemas.FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[schemas.FileItem]:
        """
        上传单文件对外包装。
        """
        target_name = new_name or local_path.name
        parent_id = target_dir.fileid or self._path_to_id(target_dir.path)
        return self._upload_single_file(
            folder_id=parent_id,
            local_path=local_path,
            target_dir_path=target_dir.path,
            target_name=target_name,
        )

    def _upload_single_file(
        self,
        folder_id: str,
        local_path: Path,
        target_dir_path: str,
        target_name: str = None,
    ) -> Optional[schemas.FileItem]:
        """
        上传单个文件。
        """
        target_name = target_name or local_path.name
        target_path = Path(target_dir_path) / target_name
        file_size = local_path.stat().st_size
        hash_md5 = md5()
        with open(local_path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(4096), b""):
                hash_md5.update(chunk)
        file_md5 = hash_md5.hexdigest().upper()

        progress_callback = transfer_process(local_path.as_posix())

        try:
            flash_response = self.client.check_flash_upload(
                task_id="",
                gcid=file_md5,
                file_size=file_size,
                file_name=target_name,
                parent_id=folder_id,
            )
            if flash_response.get("msg") == "success" and flash_response.get("data"):
                data = flash_response.get("data", {}) or {}
                progress_callback(100)
                return schemas.FileItem(
                    storage=self._disk_name,
                    fileid=str(data.get("fileId", "")),
                    path=str(target_path),
                    type="file",
                    name=data.get("fileName", target_name),
                    basename=Path(target_name).stem,
                    extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                    pickcode=str(data),
                    size=file_size,
                    modify_time=int(datetime.now().timestamp()),
                )
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】秒传检查失败: {err}")

        try:
            response = self.client.get_upload_token(
                file_name=target_name,
                file_size=file_size,
                file_md5=file_md5,
                parent_id=folder_id,
                capacity=2,
            )
            if response.get("code") == 156:
                task_id = (response.get("data", {}) or {}).get("taskId", "")
                if task_id and self._wait_task_done(task_id):
                    task_response = self.client.get_file_info_by_task_id(task_id)
                    data = task_response.get("data", {}) or {}
                    file_id = str(data.get("fileId", ""))
                    if file_id:
                        self._cache_path_id(str(target_path), file_id)
                        progress_callback(100)
                        return schemas.FileItem(
                            storage=self._disk_name,
                            fileid=file_id,
                            path=str(target_path),
                            type="file",
                            name=data.get("fileName", target_name),
                            basename=Path(target_name).stem,
                            extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                            pickcode=str(data),
                            size=file_size,
                            modify_time=int(datetime.now().timestamp()),
                        )
            if response.get("msg") != "success" and response.get("code") != 0:
                return None

            data = response.get("data", {}) or {}
            task_id = data.get("taskId", "")
            object_path = data.get("objectPath", "")
            bucket_name = data.get("bucketName", "")
            endpoint = data.get("endPoint", "") or data.get("fullEndPoint", "")
            creds = data.get("creds", {}) or {}
            access_key_id = creds.get("accessKeyID", "")
            secret_access_key = creds.get("secretAccessKey", "")
            session_token = creds.get("sessionToken", "")
            if endpoint and bucket_name and object_path and access_key_id and secret_access_key and session_token:
                parsed = urlparse(endpoint if endpoint.startswith("http") else f"https://{endpoint}")
                host = parsed.netloc or parsed.path
                if bucket_name and host.startswith(bucket_name + "."):
                    host = host[len(bucket_name) + 1 :]
                self.client.upload_file_multipart(
                    endpoint=f"https://{host}",
                    bucket_name=bucket_name,
                    object_path=object_path,
                    file_path=str(local_path),
                    oss_access_key_id=access_key_id,
                    oss_access_key_secret=secret_access_key,
                    security_token=session_token,
                    progress_callback=lambda consumed, total: progress_callback((consumed * 100) / total) if total else None,
                )
            if task_id and not self._wait_task_done(task_id):
                return None
            task_response = self.client.get_file_info_by_task_id(task_id)
            task_data = task_response.get("data", {}) or {}
            file_id = str(task_data.get("fileId", ""))
            if not file_id:
                return None
            self._cache_path_id(str(target_path), file_id)
            progress_callback(100)
            uploaded_item = schemas.FileItem(
                storage=self._disk_name,
                fileid=file_id,
                path=str(target_path),
                type="file",
                name=task_data.get("fileName", target_name),
                basename=Path(target_name).stem,
                extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                pickcode=str(task_data),
                size=file_size,
                modify_time=int(datetime.now().timestamp()),
            )
            self._cache_item(uploaded_item)
            return uploaded_item
        except Exception as err:
            logger.error(f"【光鸭云盘助手】上传失败: {target_name} - {err}")
            return None

    def upload_folder(
        self,
        target_dir: schemas.FileItem,
        local_path: Path,
    ) -> Optional[schemas.FileItem]:
        """
        上传目录。
        """
        try:
            folder = self.create_folder(target_dir, local_path.name)
            if not folder:
                return None
            success_count = 0
            fail_count = 0
            for item in local_path.iterdir():
                result = self.upload(folder, item)
                if result:
                    success_count += 1
                else:
                    fail_count += 1
            logger.info(
                f"【光鸭云盘助手】目录上传完成: {local_path.name}, 成功: {success_count}, 失败: {fail_count}"
            )
            return folder
        except Exception as err:
            logger.error(f"【光鸭云盘助手】目录上传失败: {local_path.name} - {err}")
            return None

    def detail(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取文件详情。
        """
        return self.get_item(Path(fileitem.path))

    def copy(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        复制文件或目录。
        """
        try:
            normalized_target_parent = self._normalize_path(str(path))
            target_id = self._path_to_id(normalized_target_parent)
            response = self.client.copy_file([fileitem.fileid], target_id)
            if response.get("msg") != "success" and response.get("code") != 0:
                return False
            task_id = (response.get("data", {}) or {}).get("taskId", "")
            if task_id and not self._wait_task_done(task_id, allow_missing=True):
                return False
            copied_item = self._wait_item_visible(
                parent_path=normalized_target_parent,
                name=fileitem.name,
                expected_type=fileitem.type,
            )
            if not copied_item:
                return False
            if new_name and new_name != fileitem.name:
                return self.rename(copied_item, new_name)
            return True
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】复制异常: {err}")
            return False

    def move(self, fileitem: schemas.FileItem, path: Path, new_name: str) -> bool:
        """
        移动文件或目录。
        """
        try:
            normalized_target_parent = self._normalize_path(str(path))
            normalized_source_path = self._normalize_path(fileitem.path)
            normalized_source_parent = self._normalize_path(str(Path(normalized_source_path).parent))
            current_name = fileitem.name or Path(normalized_source_path).name
            target_name = new_name or current_name

            if normalized_target_parent == normalized_source_parent:
                if target_name == current_name:
                    logger.info(
                        f"【光鸭云盘助手】跳过同目录移动空操作: {normalized_source_path} -> {normalized_target_parent}"
                    )
                    return True
                return self.rename(fileitem, target_name)

            target_id = self._path_to_id(normalized_target_parent)
            response = self.client.move_file([fileitem.fileid], target_id)
            if response.get("msg") != "success" and response.get("code") != 0:
                return False
            task_id = (response.get("data", {}) or {}).get("taskId", "")
            if task_id and not self._wait_task_done(task_id, allow_missing=True):
                return False
            self._invalidate_path_cache(fileitem.path)
            moved_item = self._wait_item_visible(
                parent_path=normalized_target_parent,
                name=fileitem.name,
                expected_type=fileitem.type,
            )
            if not moved_item:
                return False
            if target_name != fileitem.name:
                return self.rename(moved_item, target_name)
            return True
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】移动异常: {err}")
            return False

    def link(self, _fileitem: schemas.FileItem, _target_file: Path) -> bool:
        _ = (_fileitem, _target_file)
        return False

    def softlink(self, _fileitem: schemas.FileItem, _target_file: Path) -> bool:
        _ = (_fileitem, _target_file)
        return False

    def usage(self) -> Optional[schemas.StorageUsage]:
        """
        获取存储使用情况。
        """
        try:
            response = self.client.get_assets()
            if response.get("msg") != "success" and response.get("code") != 0:
                return None
            data = response.get("data", {}) or {}
            total = data.get("totalSpaceSize", 0) or 0
            used = data.get("usedSpaceSize")
            if used is None:
                return schemas.StorageUsage(total=total, available=0)
            return schemas.StorageUsage(total=total, available=total - used if total else 0)
        except Exception as err:
            logger.debug(f"【光鸭云盘助手】获取空间信息异常: {err}")
            return None

    def support_transtype(self) -> dict:
        """
        支持的整理方式。
        """
        return self.transtype

    def is_support_transtype(self, transtype: str) -> bool:
        """
        判断是否支持整理方式。
        """
        return transtype in self.transtype

# =============================================================================
# GuangYa storage API compatibility
# =============================================================================

"""MoviePilot 存储接口兼容层。

在原 GuangYaApi 实现上补齐新版 MoviePilot 接口，并增强上传完成确认与可选进度日志。
"""

import time
import threading
from datetime import datetime
from hashlib import md5
from pathlib import Path
from time import monotonic
from typing import Optional
from urllib.parse import urlparse

from app import schemas
from app.sdk.logging import logger
from app.modules.filemanager.storages import transfer_process

class _GuangYaApiV111(_LegacyGuangYaApi):
    """在原光鸭云盘实现上增加新版 MoviePilot 兼容与上传诊断。"""

    upload_progress_log: bool = False

    def get_item_strict(self, path: Path) -> Optional[schemas.FileItem]:
        """严格查询文件或目录；当前远端实现沿用 get_item 的查询语义。"""
        return self.get_item(path)

    @staticmethod
    def _fmt_bytes(size: int) -> str:
        """格式化字节大小。"""
        value = float(size or 0)
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        return f"{value:.2f} {units[index]}"

    def _record_upload_event(
        self,
        stage: str,
        target_name: str,
        message: str,
        *,
        level: str,
        status: str,
    ) -> None:
        lock = getattr(self, "_upload_event_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._upload_event_lock = lock
        events = getattr(self, "_upload_events", None)
        if events is None:
            events = []
            self._upload_events = events
        limit = int(getattr(self, "_upload_event_limit", 80) or 80)
        row = {
            "time": int(time.time()),
            "stage": str(stage or ""),
            "target_name": str(target_name or ""),
            "message": str(message or ""),
            "level": str(level or "info"),
            "status": str(status or "running"),
        }
        with lock:
            events.append(row)
            if len(events) > limit:
                del events[: len(events) - limit]

    def get_upload_diagnostics(self, limit: int = 20) -> dict:
        events = list(getattr(self, "_upload_events", []) or [])
        total = len(events)
        if limit <= 0:
            rows = []
        else:
            rows = events[-int(limit) :]
        return {
            "total_events": total,
            "recent_events": rows,
            "last_event": rows[-1] if rows else (events[-1] if events else None),
        }

    def _log_upload_stage(
        self,
        stage: str,
        target_name: str,
        message: str,
        *,
        level: str = "info",
        status: str = "running",
    ) -> None:
        text = f"【光鸭云盘助手】【上传】【{stage}】{target_name} - {message}"
        if level == "warning":
            logger.warning(text)
        elif level == "error":
            logger.error(text)
        elif level == "debug":
            logger.debug(text)
        else:
            logger.info(text)
        self._record_upload_event(stage, target_name, message, level=level, status=status)

    def _wait_task_done(
        self,
        task_id: str,
        max_try: int = 300,
        interval: int = 1,
        allow_missing: bool = False,
    ) -> bool:
        """等待远端任务完成；145/147 视为任务记录过期并立即转文件可见性确认。"""
        if not task_id:
            return True

        for index in range(max_try):
            status_response = self.client.get_task_status(task_id)
            status_code = status_response.get("code", -1)
            status_data = status_response.get("data", {}) or {}
            status = status_data.get("status")

            if status == 2:
                return True

            if self._is_task_missing(status_response):
                logger.debug(
                    "【光鸭云盘助手】任务 %s 状态记录已失效(code=%s)，转由目标文件可见性确认",
                    task_id,
                    status_code,
                )
                return True if allow_missing else False

            if status in (0, 1, 3, 145, 146, 147, 155, 163) and index < max_try - 1:
                time.sleep(interval)
                continue

            info_response = self.client.get_file_info_by_task_id(task_id)
            info_code = info_response.get("code", -1)
            info_data = info_response.get("data", {}) or {}
            if info_data.get("fileId"):
                return True

            if self._is_task_missing(info_response):
                logger.debug(
                    "【光鸭云盘助手】任务 %s 文件回执已失效(code=%s)，转由目标文件可见性确认",
                    task_id,
                    info_code,
                )
                return True if allow_missing else False

            message = status_response.get("msg") or info_response.get("msg") or ""
            logger.warning(
                "【光鸭云盘助手】任务 %s 未确认完成: status=%s code=%s/%s msg=%s",
                task_id,
                status,
                status_code,
                info_code,
                message,
            )
            return False

        logger.error("【光鸭云盘助手】任务 %s 超时", task_id)
        return False

    def _confirm_uploaded_item(
        self,
        target_dir_path: str,
        target_name: str,
        file_size: int,
        max_try: int = 90,
        interval: float = 1.0,
    ) -> Optional[schemas.FileItem]:
        """任务回执缺失时，按目标目录中的同名同大小文件兜底确认。"""
        item = self._wait_item_visible(
            parent_path=target_dir_path,
            name=target_name,
            expected_type="file",
            max_try=max_try,
            interval=interval,
        )
        if not item:
            return None
        if item.size not in (None, 0, file_size):
            logger.warning(
                "【光鸭云盘助手】【上传】发现同名文件但大小不一致: %s, local=%s, remote=%s",
                target_name,
                file_size,
                item.size,
            )
            return None
        self._cache_item(item)
        return item

    def _find_existing_uploaded_item(
        self,
        target_dir_path: str,
        target_name: str,
        file_size: int,
    ) -> Optional[schemas.FileItem]:
        """上传前检查目标是否已有同名同大小文件，避免误判失败后的重复上传。"""
        try:
            item = self._find_item_in_parent(
                parent_path=target_dir_path,
                name=target_name,
                expected_type="file",
            )
        except Exception as err:
            logger.debug("【光鸭云盘助手】【上传】预检查目标文件失败: %s - %s", target_name, err)
            return None
        if not item:
            return None
        if item.size not in (None, 0, file_size):
            return None
        self._cache_item(item)
        return item

    def _recover_upload_folder_id(self, target_dir_path: str) -> Optional[str]:
        """丢弃陈旧目录缓存，按路径重新解析；路径确实不存在时按 MoviePilot 目标路径重建。"""
        normalized_path = self._normalize_path(target_dir_path)
        self._invalidate_path_cache(normalized_path)
        try:
            folder_id = self._path_to_id(normalized_path)
            if folder_id or normalized_path == "/":
                return folder_id
        except FileNotFoundError:
            pass
        except Exception as err:
            logger.warning("【光鸭云盘助手】【上传】重新解析目标目录失败: %s - %s", normalized_path, err)

        try:
            folder = self.get_folder(Path(normalized_path))
            if folder:
                folder_id = str(folder.fileid or "")
                logger.warning(
                    "【光鸭云盘助手】【上传】目标目录已重新定位/创建: %s, fileId=%s",
                    normalized_path,
                    folder_id,
                )
                return folder_id
        except Exception as err:
            logger.warning("【光鸭云盘助手】【上传】重建目标目录失败: %s - %s", normalized_path, err)
        return None

    def _get_upload_token_with_folder_recovery(
        self,
        folder_id: str,
        target_dir_path: str,
        target_name: str,
        file_size: int,
        file_md5: str,
    ) -> tuple[dict, str]:
        """获取上传凭证；遇到 142 目录不存在时刷新目录 ID 并仅重试一次。"""
        response = self.client.get_upload_token(
            file_name=target_name,
            file_size=file_size,
            file_md5=file_md5,
            parent_id=folder_id,
            capacity=2,
        )
        if response.get("code") != 142:
            return response, folder_id

        logger.warning(
            "【光鸭云盘助手】【上传】目标目录 ID 已失效: %s, old_fileId=%s，开始按路径恢复",
            target_dir_path,
            folder_id,
        )
        recovered_id = self._recover_upload_folder_id(target_dir_path)
        if recovered_id is None:
            return response, folder_id

        response = self.client.get_upload_token(
            file_name=target_name,
            file_size=file_size,
            file_md5=file_md5,
            parent_id=recovered_id,
            capacity=2,
        )
        return response, recovered_id

    def _upload_single_file(
        self,
        folder_id: str,
        local_path: Path,
        target_dir_path: str,
        target_name: str = None,
    ) -> Optional[schemas.FileItem]:
        """上传单个文件，并提供进度、目录恢复、幂等检查与上传后可见性兜底确认。"""
        target_name = target_name or local_path.name
        normalized_target_dir = self._normalize_path(target_dir_path)
        target_path = self._normalize_path(
            f"{normalized_target_dir.rstrip('/')}/{target_name}"
            if normalized_target_dir != "/"
            else f"/{target_name}"
        )
        file_size = local_path.stat().st_size
        started_at = monotonic()

        existing = self._find_existing_uploaded_item(normalized_target_dir, target_name, file_size)
        if existing:
            self._log_upload_stage("幂等跳过", target_name, f"目标已存在同名同大小文件 fileId={existing.fileid}", status="success")
            logger.warning(
                "【光鸭云盘助手】【上传】目标已存在同名同大小文件，跳过重复上传: %s, fileId=%s",
                target_name,
                existing.fileid,
            )
            return existing

        logger.info(
            "【光鸭云盘助手】【上传】开始: %s -> %s, 大小=%s",
            local_path,
            target_path,
            self._fmt_bytes(file_size),
        )
        self._log_upload_stage("准备", target_name, f"目标={normalized_target_dir}, 大小={self._fmt_bytes(file_size)}")

        hash_md5 = md5()
        with open(local_path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(4 * 1024 * 1024), b""):
                hash_md5.update(chunk)
        file_md5 = hash_md5.hexdigest().upper()

        if self.upload_progress_log:
            logger.info("【光鸭云盘助手】【上传】MD5 完成: %s, md5=%s", target_name, file_md5)

        mp_progress = transfer_process(target_path)
        last_logged_bucket = -1

        def progress(consumed: int, total: int) -> None:
            """同时上报 MoviePilot 进度，并按 5%% 粒度输出日志。"""
            nonlocal last_logged_bucket
            if not total:
                return
            percent = max(0.0, min(100.0, consumed * 100 / total))
            mp_progress(percent)
            if not self.upload_progress_log:
                return
            bucket = int(percent // 5) * 5
            if bucket <= last_logged_bucket and percent < 100:
                return
            last_logged_bucket = bucket
            elapsed = max(monotonic() - started_at, 0.001)
            speed = consumed / elapsed
            logger.info(
                "【光鸭云盘助手】【上传】进度: %s %d%% (%s/%s), 平均速度=%s/s",
                target_name,
                int(percent),
                self._fmt_bytes(consumed),
                self._fmt_bytes(total),
                self._fmt_bytes(speed),
            )

        try:
            flash_response = self.client.check_flash_upload(
                task_id="",
                gcid=file_md5,
                file_size=file_size,
                file_name=target_name,
                parent_id=folder_id,
            )
            if flash_response.get("msg") == "success" and flash_response.get("data"):
                data = flash_response.get("data", {}) or {}
                mp_progress(100)
                elapsed = monotonic() - started_at
                self._log_upload_stage("秒传", target_name, f"成功 fileId={data.get('fileId', '')}, 耗时={elapsed:.2f}s", status="success")
                logger.info(
                    "【光鸭云盘助手】【上传】秒传成功: %s, fileId=%s, 耗时=%.2fs",
                    target_name,
                    data.get("fileId", ""),
                    elapsed,
                )
                return schemas.FileItem(
                    storage=self._disk_name,
                    fileid=str(data.get("fileId", "")),
                    path=target_path,
                    type="file",
                    name=data.get("fileName", target_name),
                    basename=Path(target_name).stem,
                    extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                    pickcode=str(data),
                    size=file_size,
                    modify_time=int(datetime.now().timestamp()),
                )
        except Exception as err:
            logger.debug("【光鸭云盘助手】【上传】秒传检查失败: %s - %s", target_name, err)

        try:
            self._log_upload_stage("凭证", target_name, "开始获取上传凭证")
            response, folder_id = self._get_upload_token_with_folder_recovery(
                folder_id=folder_id,
                target_dir_path=normalized_target_dir,
                target_name=target_name,
                file_size=file_size,
                file_md5=file_md5,
            )

            if response.get("code") == 156:
                task_id = (response.get("data", {}) or {}).get("taskId", "")
                if self.upload_progress_log:
                    logger.info("【光鸭云盘助手】【上传】服务端任务已存在: %s, task_id=%s", target_name, task_id)
                if task_id:
                    self._log_upload_stage("任务确认", target_name, f"复用服务端任务 task_id={task_id}")
                    self._wait_task_done(task_id, allow_missing=True)
                    task_response = self.client.get_file_info_by_task_id(task_id)
                    data = task_response.get("data", {}) or {}
                    file_id = str(data.get("fileId", ""))
                    if file_id:
                        self._cache_path_id(target_path, file_id)
                        mp_progress(100)
                        self._log_upload_stage("完成", target_name, f"任务回执成功 fileId={file_id}", status="success")
                        logger.info("【光鸭云盘助手】【上传】任务完成: %s, fileId=%s", target_name, file_id)
                        return schemas.FileItem(
                            storage=self._disk_name,
                            fileid=file_id,
                            path=target_path,
                            type="file",
                            name=data.get("fileName", target_name),
                            basename=Path(target_name).stem,
                            extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                            pickcode=str(data),
                            size=file_size,
                            modify_time=int(datetime.now().timestamp()),
                        )
                confirmed = self._confirm_uploaded_item(normalized_target_dir, target_name, file_size)
                if confirmed:
                    mp_progress(100)
                    self._log_upload_stage("目录确认", target_name, f"任务回执缺失，按目录可见性确认成功 fileId={confirmed.fileid}", status="success")
                    logger.info("【光鸭云盘助手】【上传】通过目录可见性确认成功: %s, fileId=%s", target_name, confirmed.fileid)
                    return confirmed

            if response.get("msg") != "success" and response.get("code") != 0:
                logger.error("【光鸭云盘助手】【上传】获取上传凭证失败: %s - %s", target_name, response)
                return None

            data = response.get("data", {}) or {}
            task_id = data.get("taskId", "")
            object_path = data.get("objectPath", "")
            bucket_name = data.get("bucketName", "")
            endpoint = data.get("endPoint", "") or data.get("fullEndPoint", "")
            creds = data.get("creds", {}) or {}
            access_key_id = creds.get("accessKeyID", "")
            secret_access_key = creds.get("secretAccessKey", "")
            session_token = creds.get("sessionToken", "")

            if self.upload_progress_log:
                logger.info("【光鸭云盘助手】【上传】凭证获取成功: %s, task_id=%s", target_name, task_id)

            if endpoint and bucket_name and object_path and access_key_id and secret_access_key and session_token:
                self._log_upload_stage("分片上传", target_name, f"开始上传到 bucket={bucket_name}, task_id={task_id or 'none'}")
                parsed = urlparse(endpoint if endpoint.startswith("http") else f"https://{endpoint}")
                host = parsed.netloc or parsed.path
                if bucket_name and host.startswith(bucket_name + "."):
                    host = host[len(bucket_name) + 1 :]
                self.client.upload_file_multipart(
                    endpoint=f"https://{host}",
                    bucket_name=bucket_name,
                    object_path=object_path,
                    file_path=str(local_path),
                    oss_access_key_id=access_key_id,
                    oss_access_key_secret=secret_access_key,
                    security_token=session_token,
                    progress_callback=progress,
                )
            else:
                missing_fields = [
                    name
                    for name, value in (
                        ("endPoint", endpoint),
                        ("bucketName", bucket_name),
                        ("objectPath", object_path),
                        ("accessKeyID", access_key_id),
                        ("secretAccessKey", secret_access_key),
                        ("sessionToken", session_token),
                    )
                    if not value
                ]
                logger.error(
                    "【光鸭云盘助手】【上传】上传凭证缺少关键字段，无法执行分片上传: %s, file=%s, task_id=%s",
                    ",".join(missing_fields),
                    target_name,
                    task_id or "none",
                )
                self._log_upload_stage(
                    "凭证异常",
                    target_name,
                    f"上传凭证缺少关键字段: {','.join(missing_fields)}",
                    level="error",
                    status="error",
                )
                return None

            if task_id:
                self._log_upload_stage("任务确认", target_name, f"等待云端任务完成 task_id={task_id}")
                self._wait_task_done(task_id, allow_missing=True)
                task_response = self.client.get_file_info_by_task_id(task_id)
                task_data = task_response.get("data", {}) or {}
                file_id = str(task_data.get("fileId", ""))
                if file_id:
                    self._cache_path_id(target_path, file_id)
                    mp_progress(100)
                    uploaded_item = schemas.FileItem(
                        storage=self._disk_name,
                        fileid=file_id,
                        path=target_path,
                        type="file",
                        name=task_data.get("fileName", target_name),
                        basename=Path(target_name).stem,
                        extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                        pickcode=str(task_data),
                        size=file_size,
                        modify_time=int(datetime.now().timestamp()),
                    )
                    self._cache_item(uploaded_item)
                    elapsed = max(monotonic() - started_at, 0.001)
                    logger.info(
                        "【光鸭云盘助手】【上传】完成: %s, fileId=%s, 耗时=%.2fs, 平均速度=%s/s",
                        target_name,
                        file_id,
                        elapsed,
                        self._fmt_bytes(file_size / elapsed),
                    )
                    self._log_upload_stage("完成", target_name, f"任务确认成功 fileId={file_id}, 耗时={elapsed:.2f}s", status="success")
                    return uploaded_item

            confirmed = self._confirm_uploaded_item(normalized_target_dir, target_name, file_size)
            if confirmed:
                mp_progress(100)
                elapsed = max(monotonic() - started_at, 0.001)
                self._log_upload_stage("目录确认", target_name, f"任务无 fileId，按目录确认成功 fileId={confirmed.fileid}")
                logger.warning(
                    "【光鸭云盘助手】【上传】任务回执缺少 fileId，但目标文件已确认存在，按成功返回: %s, fileId=%s, 耗时=%.2fs",
                    target_name,
                    confirmed.fileid,
                    elapsed,
                )
                self._log_upload_stage("完成", target_name, f"目录确认成功 fileId={confirmed.fileid}, 耗时={elapsed:.2f}s", status="success")
                return confirmed

            self._log_upload_stage("失败", target_name, "上传后 90 秒仍未确认目标文件", level="error", status="error")
            logger.error("【光鸭云盘助手】【上传】失败: %s，上传后 90 秒仍未确认目标文件", target_name)
            return None
        except Exception as err:
            confirmed = self._confirm_uploaded_item(normalized_target_dir, target_name, file_size, max_try=30)
            if confirmed:
                mp_progress(100)
                self._log_upload_stage("异常恢复", target_name, f"出现异常但目录确认成功: {err}", level="warning")
                logger.warning(
                    "【光鸭云盘助手】【上传】过程出现异常但目标文件已存在，按成功返回: %s, error=%s",
                    target_name,
                    err,
                )
                self._log_upload_stage("完成", target_name, f"异常恢复后确认成功 fileId={confirmed.fileid}", status="success")
                return confirmed
            self._log_upload_stage("失败", target_name, str(err), level="error", status="error")
            logger.error("【光鸭云盘助手】【上传】失败: %s - %s", target_name, err)
            return None

# =============================================================================
# GuangYa storage API stable layer
# =============================================================================

"""光鸭云盘助手 v1.1.2 回收站稳定性适配层。

只覆盖彻底删除链路：区分“回收站查询失败”和“查询成功但目标已不存在”，
避免网络/DNS异常时误判成功，也避免目标已被清理时持续输出假失败告警。
"""

import time
from typing import List, Optional, Tuple

from app import schemas
from app.sdk.logging import logger

class _GuangYaApiV112(_GuangYaApiV111):
    """在 v1.1.1 API 上增加回收站幂等彻底删除保护。"""

    def _iter_recycle_items_checked(self) -> Tuple[List[schemas.FileItem], bool]:
        """读取完整回收站并返回 ``(items, query_ok)``。

        ``query_ok=False`` 表示至少一页请求本身失败，此时绝不能把“空列表”解释为
        “目标已经不存在”。只有查询明确成功时，空列表才是可信终态。
        """
        results: List[schemas.FileItem] = []
        page = 1
        while True:
            response = self.client.get_file_list(
                parent_id="",
                page_size=self._page_size,
                order_by=10,
                sort_type=0,
                file_types=[],
                page=page,
                dir_type=4,
            )
            if response.get("code", -1) != 0 and response.get("msg") != "success":
                return results, False

            data = response.get("data", {}) or {}
            item_list = data.get("list", []) or []
            if not item_list:
                return results, True

            for item in item_list:
                recycle_item = self._build_file_item_from_api("/", item)
                recycle_item.path = self._build_path(
                    "/.recycle_bin",
                    recycle_item.name,
                    recycle_item.type == "dir",
                )
                results.append(recycle_item)

            total = data.get("total") or 0
            if len(item_list) < self._page_size or (total and len(results) >= total):
                return results, True
            page += 1

    def _match_recycle_item_checked(
        self,
        fileitem: schemas.FileItem,
    ) -> Tuple[Optional[schemas.FileItem], bool]:
        """优先按 fileId 匹配回收站项目，并保留查询成功状态。"""
        candidates, query_ok = self._iter_recycle_items_checked()
        if not query_ok:
            return None, False

        target_fileid = str(fileitem.fileid or "")
        target_name = str(fileitem.name or "")
        target_size = fileitem.size

        if target_fileid:
            for item in candidates:
                if str(item.fileid or "") == target_fileid:
                    return item, True

        same_name_items = [item for item in candidates if item.name == target_name]
        if len(same_name_items) == 1:
            return same_name_items[0], True

        if target_size is not None:
            sized_items = [item for item in same_name_items if item.size == target_size]
            if len(sized_items) == 1:
                return sized_items[0], True

        return None, True

    def _purge_from_recycle(
        self,
        fileitem: schemas.FileItem,
        max_try: int = 8,
        interval: float = 1.0,
    ) -> bool:
        """幂等彻底删除。

        查询失败与目标不存在必须分开处理：
        - 查询失败：不做成功推断；
        - 查询成功且目标持续不存在：认为已经被其它流程清理，按成功终态返回；
        - 找到目标：执行永久删除并确认任务。
        """
        recycle_item: Optional[schemas.FileItem] = None
        last_query_ok = False

        for index in range(max_try):
            recycle_item, query_ok = self._match_recycle_item_checked(fileitem)
            last_query_ok = query_ok
            if recycle_item:
                break

            if not query_ok:
                logger.debug(
                    "【光鸭云盘助手】回收站查询暂时失败，第 %d/%d 次: %s",
                    index + 1,
                    max_try,
                    fileitem.name,
                )

            if index < max_try - 1:
                time.sleep(interval)

        if not recycle_item:
            if last_query_ok:
                logger.info(
                    "【光鸭云盘助手】回收站查询正常且目标已不存在，按已彻底清理处理: %s",
                    fileitem.name,
                )
                return True

            logger.warning(
                "【光鸭云盘助手】回收站查询连续失败，无法确认彻底删除状态，保留后续重试: %s",
                fileitem.name,
            )
            return False

        response = self.client.delete_file([recycle_item.fileid])
        if response.get("msg") != "success" and response.get("code") != 0:
            # 删除接口若明确表示目标不存在，也符合幂等删除语义。
            if self._is_task_missing(response) or response.get("code") in (142, 145, 147):
                logger.info(
                    "【光鸭云盘助手】回收站目标在彻底删除阶段已不存在，按成功处理: %s",
                    fileitem.name,
                )
                return True
            logger.warning("【光鸭云盘助手】回收站彻底删除失败: %s", response)
            return False

        task_id = (response.get("data", {}) or {}).get("taskId", "")
        if task_id and not self._wait_task_done(task_id, allow_missing=True):
            return False
        return True


__all__ = ["GuangYaApi"]


# =============================================================================
# GuangYa storage safety (direct V4 implementation)
# =============================================================================

def _guangya_response_success(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    return response.get("code", -1) == 0 or response.get("msg") == "success"


def _guangya_response_error(response: Any) -> str:
    if not isinstance(response, dict):
        return repr(response)
    return str(
        response.get("error")
        or response.get("msg")
        or response.get("message")
        or f"code={response.get('code')}"
    )


def _guangya_page_has_more(
    data: Dict[str, Any],
    page_size: int,
    page_items: int,
    accumulated: int,
) -> bool:
    try:
        total = int(data.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    if page_items <= 0:
        return False
    if total > 0:
        return accumulated < total
    return page_items >= page_size


class GuangYaApi(_GuangYaApiV112):
    """V4 光鸭存储 API。

    把 v3.6.9 已验证的分页路径解析、实例缓存隔离、严格目录读取直接并入类实现，
    不再通过 import-time monkey patch 修改方法。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # 旧实现使用类属性缓存。V4 明确改为实例缓存，避免账号切换/热重载污染。
        self._id_cache = {}
        self._item_cache = {}
        self._move_delete_protection: Dict[str, Dict[str, Any]] = {}
        self._move_delete_lock = threading.RLock()

    @staticmethod
    def _same_remote_identity(expected: Any, actual: Any) -> bool:
        """优先按 fileId 比对，缺失时使用非零文件大小兜底。"""
        expected_id = str(getattr(expected, "fileid", "") or "")
        actual_id = str(getattr(actual, "fileid", "") or "")
        if expected_id and actual_id:
            return expected_id == actual_id
        expected_size = getattr(expected, "size", None)
        actual_size = getattr(actual, "size", None)
        if expected_size not in (None, 0) and actual_size not in (None, 0):
            return int(expected_size) == int(actual_size)
        return True

    def _delete_protection_keys(self, fileitem: Any) -> List[str]:
        """生成移动状态不确定时的删除保护键。"""
        keys: List[str] = []
        fileid = str(getattr(fileitem, "fileid", "") or "")
        path = str(getattr(fileitem, "path", "") or "")
        if fileid:
            keys.append(f"id:{fileid}")
        if path:
            keys.append(f"path:{self._normalize_path(path)}")
        return keys

    def _protect_from_delete(
        self,
        fileitem: Any,
        *,
        reason: str,
        extra_paths: Optional[List[str]] = None,
    ) -> None:
        """移动/重命名结果不确定时冻结该 fileId/path 的 delete/purge。"""
        record = {
            "reason": str(reason or "remote_state_uncertain"),
            "time": time.time(),
            "fileid": str(getattr(fileitem, "fileid", "") or ""),
            "path": self._normalize_path(str(getattr(fileitem, "path", "") or "/")),
        }
        keys = self._delete_protection_keys(fileitem)
        for value in extra_paths or []:
            if value:
                keys.append(f"path:{self._normalize_path(value)}")
        with self._move_delete_lock:
            for key in keys:
                self._move_delete_protection[key] = dict(record)
        logger.error(
            "【光鸭云盘助手】【数据保护】远端移动/重命名状态未确认，冻结删除: %s reason=%s",
            record["path"],
            record["reason"],
        )

    def _clear_delete_protection(self, fileitem: Any, *paths: str) -> None:
        """操作获得确定成功终态后解除当前事务留下的保护键。"""
        keys = self._delete_protection_keys(fileitem)
        keys.extend(
            f"path:{self._normalize_path(value)}"
            for value in paths
            if value
        )
        with self._move_delete_lock:
            for key in keys:
                self._move_delete_protection.pop(key, None)

    def _delete_protection_record(self, fileitem: Any) -> Optional[Dict[str, Any]]:
        """读取 fileId/path 命中的数据保护记录。"""
        with self._move_delete_lock:
            for key in self._delete_protection_keys(fileitem):
                record = self._move_delete_protection.get(key)
                if record:
                    return dict(record)
        return None

    def _find_item_in_parent_strict(
        self,
        *,
        parent_path: str,
        name: Optional[str] = None,
        expected_type: Optional[str] = None,
        expected_fileid: Optional[str] = None,
    ) -> Optional[Any]:
        """严格读取父目录并匹配名称/类型/fileId；读取失败向上抛出。"""
        normalized_parent = self._normalize_path(parent_path)
        parent = self.refresh_item(Path(normalized_parent))
        if not parent:
            return None
        for item in self.list_strict(parent):
            if name is not None and str(getattr(item, "name", "") or "") != str(name):
                continue
            if expected_type and str(getattr(item, "type", "") or "") != str(expected_type):
                continue
            if expected_fileid and str(getattr(item, "fileid", "") or "") != str(expected_fileid):
                continue
            return item
        return None

    def _confirmed_named_item(
        self,
        *,
        parent_path: str,
        target_name: str,
        source_item: Any,
        compare_fileid: bool,
        max_try: int = 30,
        interval: float = 0.5,
    ) -> Optional[Any]:
        """确认 MoviePilot 目标名在远端真实可见，并校验文件身份。"""
        for index in range(max_try):
            try:
                item = self._find_item_in_parent_strict(
                    parent_path=parent_path,
                    name=target_name,
                    expected_type=getattr(source_item, "type", None),
                )
            except Exception as err:
                logger.debug(
                    "【光鸭云盘助手】【远端确认】第 %s/%s 次读取失败: %s/%s - %s",
                    index + 1,
                    max_try,
                    parent_path,
                    target_name,
                    err,
                )
                item = None
            if item:
                if compare_fileid:
                    if self._same_remote_identity(source_item, item):
                        self._cache_item(item)
                        return item
                else:
                    expected_size = getattr(source_item, "size", None)
                    actual_size = getattr(item, "size", None)
                    if (
                        expected_size in (None, 0)
                        or actual_size in (None, 0)
                        or int(expected_size) == int(actual_size)
                    ):
                        self._cache_item(item)
                        return item
            if index < max_try - 1:
                time.sleep(interval)
        return None

    def rename(self, fileitem: Any, name: str) -> bool:
        """重命名只有在真实目标名可见后才向 MoviePilot 返回成功。"""
        old_path = self._normalize_path(str(getattr(fileitem, "path", "") or ""))
        parent_path = self._normalize_path(str(Path(old_path).parent))
        current_name = str(getattr(fileitem, "name", "") or Path(old_path).name)
        target_name = str(name or current_name).strip()
        if not target_name:
            return False
        if target_name == current_name:
            return True

        target_path = self._normalize_path(str(Path(parent_path) / target_name))
        if not super().rename(fileitem, target_name):
            self._protect_from_delete(
                fileitem,
                reason="rename_api_failed_or_uncertain",
                extra_paths=[target_path],
            )
            return False

        # 基类会写入理论缓存，确认前必须清理，避免用缓存冒充远端终态。
        self._invalidate_path_cache(old_path)
        self._invalidate_path_cache(target_path)
        confirmed = self._confirmed_named_item(
            parent_path=parent_path,
            target_name=target_name,
            source_item=fileitem,
            compare_fileid=True,
        )
        if confirmed:
            self._clear_delete_protection(fileitem, old_path, target_path)
            logger.info(
                "【光鸭云盘助手】【重命名确认】远端已确认: %s -> %s",
                current_name,
                target_name,
            )
            return True

        self._protect_from_delete(
            fileitem,
            reason="rename_target_not_confirmed",
            extra_paths=[old_path, target_path],
        )
        logger.error(
            "【光鸭云盘助手】【重命名确认】接口返回后仍未确认远端目标名，拒绝返回成功: %s -> %s",
            old_path,
            target_path,
        )
        return False

    def move_item(
        self,
        fileitem: Any,
        path: Path,
        new_name: str,
    ) -> Optional[Any]:
        """MoviePilot 同盘移动：执行、目标可见性、命名三步均确认后才返回 FileItem。"""
        source_path = self._normalize_path(str(getattr(fileitem, "path", "") or ""))
        source_parent = self._normalize_path(str(Path(source_path).parent))
        target_parent = self._normalize_path(str(path))
        current_name = str(getattr(fileitem, "name", "") or Path(source_path).name)
        target_name = str(new_name or current_name)

        if source_parent == target_parent:
            if target_name == current_name:
                try:
                    return self.refresh_item(Path(source_path)) or fileitem
                except Exception:
                    return fileitem
            if not self.rename(fileitem, target_name):
                return None
            return self._confirmed_named_item(
                parent_path=target_parent,
                target_name=target_name,
                source_item=fileitem,
                compare_fileid=True,
            )

        target_current_path = self._normalize_path(
            str(Path(target_parent) / current_name)
        )
        target_final_path = self._normalize_path(
            str(Path(target_parent) / target_name)
        )
        try:
            target_id = self._path_to_id(target_parent)
            response = self.client.move_file([fileitem.fileid], target_id)
        except Exception as err:
            self._protect_from_delete(
                fileitem,
                reason=f"move_request_exception:{err}",
                extra_paths=[target_current_path, target_final_path],
            )
            return None

        if not _guangya_response_success(response):
            self._protect_from_delete(
                fileitem,
                reason=f"move_api_failed:{_guangya_response_error(response)}",
                extra_paths=[target_current_path, target_final_path],
            )
            return None

        task_id = str((response.get("data", {}) or {}).get("taskId") or "")
        task_confirmed = True
        if task_id:
            task_confirmed = self._wait_task_done(task_id, allow_missing=True)

        self._invalidate_path_cache(source_path)
        self._invalidate_path_cache(target_current_path)
        self._invalidate_path_cache(target_final_path)

        moved_item = self._confirmed_named_item(
            parent_path=target_parent,
            target_name=current_name,
            source_item=fileitem,
            compare_fileid=True,
        )
        if not moved_item:
            # 失败前再次确认源是否还在；无论哪种情况都冻结 delete，避免失败清理误删同 fileId。
            try:
                source_actual = self._find_item_in_parent_strict(
                    parent_path=source_parent,
                    name=current_name,
                    expected_type=getattr(fileitem, "type", None),
                    expected_fileid=str(getattr(fileitem, "fileid", "") or "") or None,
                )
            except Exception:
                source_actual = None
            reason = (
                "move_target_not_confirmed_source_visible"
                if source_actual
                else "move_visibility_uncertain"
            )
            if not task_confirmed:
                reason = f"{reason}_task_unconfirmed"
            self._protect_from_delete(
                fileitem,
                reason=reason,
                extra_paths=[source_path, target_current_path, target_final_path],
            )
            return None

        final_item = moved_item
        if target_name != current_name:
            if not self.rename(moved_item, target_name):
                self._protect_from_delete(
                    moved_item,
                    reason="move_succeeded_but_rename_unconfirmed",
                    extra_paths=[source_path, target_current_path, target_final_path],
                )
                return None
            final_item = self._confirmed_named_item(
                parent_path=target_parent,
                target_name=target_name,
                source_item=fileitem,
                compare_fileid=True,
            )
            if not final_item:
                self._protect_from_delete(
                    moved_item,
                    reason="move_final_target_not_confirmed",
                    extra_paths=[source_path, target_current_path, target_final_path],
                )
                return None

        self._clear_delete_protection(
            fileitem,
            source_path,
            target_current_path,
            target_final_path,
        )
        logger.info(
            "【光鸭云盘助手】【移动终态】已确认远端目标: %s -> %s",
            source_path,
            target_final_path,
        )
        return final_item

    def copy_item(
        self,
        fileitem: Any,
        path: Path,
        new_name: str,
    ) -> Optional[Any]:
        """MoviePilot 同盘复制：复制品必须按目标名和大小真实可见。"""
        target_parent = self._normalize_path(str(path))
        current_name = str(getattr(fileitem, "name", "") or "")
        target_name = str(new_name or current_name)
        target_current_path = self._normalize_path(str(Path(target_parent) / current_name))
        target_final_path = self._normalize_path(str(Path(target_parent) / target_name))
        try:
            target_id = self._path_to_id(target_parent)
            response = self.client.copy_file([fileitem.fileid], target_id)
        except Exception as err:
            logger.error("【光鸭云盘助手】【复制终态】复制请求异常: %s", err)
            return None
        if not _guangya_response_success(response):
            logger.error(
                "【光鸭云盘助手】【复制终态】复制接口失败: %s",
                _guangya_response_error(response),
            )
            return None

        task_id = str((response.get("data", {}) or {}).get("taskId") or "")
        if task_id and not self._wait_task_done(task_id, allow_missing=True):
            logger.warning("【光鸭云盘助手】【复制终态】任务状态未确认，继续按远端可见性核验")

        self._invalidate_path_cache(target_current_path)
        self._invalidate_path_cache(target_final_path)
        copied_item = self._confirmed_named_item(
            parent_path=target_parent,
            target_name=current_name,
            source_item=fileitem,
            compare_fileid=False,
        )
        if not copied_item:
            logger.error(
                "【光鸭云盘助手】【复制终态】接口返回后目标副本不可见: %s",
                target_current_path,
            )
            return None

        final_item = copied_item
        if target_name != current_name:
            if not self.rename(copied_item, target_name):
                return None
            final_item = self._confirmed_named_item(
                parent_path=target_parent,
                target_name=target_name,
                source_item=fileitem,
                compare_fileid=False,
            )
        if not final_item:
            logger.error(
                "【光鸭云盘助手】【复制终态】最终 MoviePilot 目标名未确认: %s",
                target_final_path,
            )
            return None
        return final_item

    def move(self, fileitem: Any, path: Path, new_name: str) -> bool:
        """兼容旧 Storage 调用；核心语义统一由 move_item 提供。"""
        return self.move_item(fileitem, path, new_name) is not None

    def copy(self, fileitem: Any, path: Path, new_name: str) -> bool:
        """兼容旧 Storage 调用；核心语义统一由 copy_item 提供。"""
        return self.copy_item(fileitem, path, new_name) is not None

    def delete(self, fileitem: Any) -> bool:
        """移动状态不确定的 fileId/path 禁止进入回收站。"""
        protected = self._delete_protection_record(fileitem)
        if protected:
            logger.error(
                "【光鸭云盘助手】【数据保护】阻止删除未确认移动项: %s reason=%s",
                str(getattr(fileitem, "path", "") or ""),
                protected.get("reason") or "unknown",
            )
            return False
        return super().delete(fileitem)

    def _schedule_purge_from_recycle(self, fileitem: Any, *args: Any, **kwargs: Any) -> None:
        """受保护项禁止进入永久删除队列。"""
        if self._delete_protection_record(fileitem):
            logger.error(
                "【光鸭云盘助手】【数据保护】阻止未确认移动项加入永久删除队列: %s",
                str(getattr(fileitem, "path", "") or ""),
            )
            return None
        return super()._schedule_purge_from_recycle(fileitem, *args, **kwargs)

    def _purge_from_recycle(self, fileitem: Any, *args: Any, **kwargs: Any) -> bool:
        """永久删除执行前再次检查事务保护。"""
        if self._delete_protection_record(fileitem):
            logger.error(
                "【光鸭云盘助手】【数据保护】阻止永久删除未确认移动项: %s",
                str(getattr(fileitem, "path", "") or ""),
            )
            return False
        return super()._purge_from_recycle(fileitem, *args, **kwargs)

    def _path_to_id(self, path: str) -> str:
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
                if not _guangya_response_success(response):
                    raise RuntimeError(
                        f"【光鸭云盘助手】解析路径 {normalized_path} 时读取目录失败: "
                        f"parent={current_path} page={page} "
                        f"error={_guangya_response_error(response)}"
                    )

                data = dict(response.get("data") or {})
                items = list(data.get("list") or [])
                accumulated += len(items)
                for raw in items:
                    if str(raw.get("fileName") or "") == part:
                        found = dict(raw)
                        break
                if found is not None:
                    break
                if not _guangya_page_has_more(
                    data, self._page_size, len(items), accumulated
                ):
                    break
                page += 1

            if found is None:
                raise FileNotFoundError(f"【光鸭云盘助手】{normalized_path} 不存在")

            current_id = str(found.get("fileId") or "")
            current_path = (
                f"{current_path.rstrip('/')}/{part}"
                if current_path != "/"
                else f"/{part}"
            )
            self._cache_path_id(current_path, current_id)
            parent_path = str(Path(current_path).parent).replace("\\", "/") or "/"
            self._build_file_item_from_api(parent_path, found)

        return current_id

    def list_strict(self, fileitem: Any) -> List[Any]:
        """完整分页读取；上游错误必须抛出，不能伪装成成功的空目录。"""
        if str(getattr(fileitem, "type", "") or "") == "file":
            item = self.detail(fileitem)
            return [item] if item else []

        normalized_dir_path = self._normalize_path(getattr(fileitem, "path", "/"))
        file_id = self._normalize_fileid(
            getattr(fileitem, "fileid", ""), normalized_dir_path
        )
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
            if not _guangya_response_success(response):
                raise RuntimeError(
                    f"【光鸭云盘助手】读取目录失败: "
                    f"path={normalized_dir_path} page={page} "
                    f"error={_guangya_response_error(response)}"
                )
            data = dict(response.get("data") or {})
            item_list = list(data.get("list") or [])
            for raw in item_list:
                results.append(
                    self._build_file_item_from_api(normalized_dir_path, raw)
                )
            if not _guangya_page_has_more(
                data, self._page_size, len(item_list), len(results)
            ):
                break
            page += 1
        return results

    def get_item(self, path: Path):
        normalized = self._normalize_path(str(path))
        if normalized == "/":
            return super().get_item(path)

        cached_item = self._restore_cached_item(normalized)
        if cached_item:
            return cached_item

        try:
            file_id = self._path_to_id(normalized)
        except FileNotFoundError:
            return None

        resolved = self._restore_cached_item(normalized)
        if resolved and str(getattr(resolved, "fileid", "") or "") == str(file_id or ""):
            return resolved
        return super().get_item(path)

    def refresh_item(self, path: Path):
        normalized = self._normalize_path(str(path))
        self._invalidate_path_cache(normalized)
        return self.get_item(Path(normalized))


# =============================================================================
# WebDAV provider
# =============================================================================

"""
光鸭云盘 WebDAV 适配器

将光鸭云盘 API 适配为标准 WebDAV 文件系统接口，
供 Emby / Jellyfin 等媒体服务器通过 WebDAV 协议直接挂载和播放。

支持的 WebDAV 方法:
- PROPFIND: 列目录/获取文件属性（Emby 扫描媒体库时使用）
- GET:       下载/播放文件（流式代理）
- HEAD:      获取文件元信息
- MKCOL:     创建目录（可选）
- DELETE:    删除文件（可选）
- MOVE:      移动/重命名（可选）
- PUT:       上传文件（可选）
"""

import os
import time
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import Request, Response
from fastapi.responses import Response, StreamingResponse

from app.sdk.logging import logger

# WebDAV XML 命名空间
DAV_NS = "DAV:"
NSMAP = {"d": DAV_NS}


class GuangyaWebDAVProvider:
    """
    光鸭云盘 → WebDAV 适配器。
    
    将 GuangYaApi 的文件操作映射为 WebDAV HTTP 接口，
    使 Emby 等支持 WebDAV 的应用可以直接挂载光鸭云盘。
    """

    def __init__(self, guangya_api, client):
        self._api = guangya_api
        self._client = client

    def handle_request(self, request: Request, path: str = "") -> Response:
        """
        分发 WebDAV 请求到对应的方法处理器。
        """
        method = request.method.upper()

        # 规范化路径
        normalized_path = str(path or "").replace("\\", "/").strip()
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        normalized_path = normalized_path.rstrip("/") or "/"

        logger.debug(f"【光鸭云盘助手】【WebDAV】{method} {normalized_path}")

        handlers = {
            "OPTIONS": self._handle_options,
            "PROPFIND": self._handle_propfind,
            "GET": self._handle_get,
            "HEAD": self._handle_head,
            "MKCOL": self._handle_mkcol,
            "DELETE": self._handle_delete,
            "PUT": self._handle_put,
            "MOVE": self._handle_move,
            "COPY": self._handle_copy,
        }

        handler = handlers.get(method)
        if not handler:
            return Response(
                content=f"Method {method} not allowed",
                status_code=405,
                headers={"Allow": ", ".join(handlers.keys())},
            )

        try:
            return handler(request, normalized_path)
        except Exception as err:
            logger.error(f"【光鸭云盘助手】【WebDAV】{method} {normalized_path} 失败: {err}")
            return Response(
                content=f'<?xml version="1.0" encoding="utf-8"?>\n'
                        f'<d:error xmlns:d="DAV:"><s:message>{str(err)}</s:message></d:error>',
                status_code=500,
                media_type="application/xml; charset=utf-8",
            )

    # ------------------------------------------------------------------
    # OPTIONS
    # ------------------------------------------------------------------
    @staticmethod
    def _handle_options(_request: Request, _path: str) -> Response:
        """返回服务器支持的 WebDAV 能力。"""
        return Response(
            status_code=200,
            headers={
                "Allow": "OPTIONS, PROPFIND, GET, HEAD, MKCOL, DELETE, PUT, MOVE, COPY",
                "DAV": "1,2",
                "MS-Author-Via": "DAV",
            },
        )

    # ------------------------------------------------------------------
    # PROPFIND — 核心：Emby/Jellyfin 用它扫描目录
    # ------------------------------------------------------------------
    def _handle_propfind(self, request: Request, path: str) -> Response:
        """
        列出目录内容或获取文件属性。
        
        Emby 在扫描 WebDAV 媒体库时会大量调用此方法：
        - depth:0 → 获取当前路径自身的属性
        - depth:1 → 列出直接子项
        """
        from pathlib import Path as PathLib

        depth = request.headers.get("depth", "1").strip()

        # 解析请求体（可能包含需要查询的属性列表）
        requested_props = self._parse_propfind_request(request)

        item = self._api.get_item(PathLib(path))
        if not item:
            return Response(status_code=404)

        # 构建多状态响应
        responses: List[Element] = []

        # 当前路径自身
        responses.append(self._build_propstat_response(path, item, requested_props))

        # 如果是目录且 depth != "0"，列出子项
        if item.type == "dir" and depth != "0":
            children = self._api.list(item)
            for child in (children or []):
                child_path = child.path if child.path else f"{path.rstrip('/')}/{child.name}"
                responses.append(self._build_propstat_response(child_path, child, requested_props))

        # 构建 XML 响应
        multistatus = Element(f"{{{DAV_NS}}}multistatus")
        for resp in responses:
            multistatus.append(resp)

        xml_str = tostring(multistatus, encoding="unicode", xml_declaration=False)
        pretty_xml = self._prettify_xml(xml_str)

        return Response(
            content=f'<?xml version="1.0" encoding="utf-8"?>\n{pretty_xml}',
            status_code=207,  # Multi-Status
            media_type="application/xml; charset=utf-8",
            headers={"DAV": "1,2"},
        )

    def _parse_propfind_request(self, request: Request) -> List[str]:
        """
        解析 PROPFIND 请求体中请求的属性列表。
        返回空列表表示 allprop。
        """
        try:
            body = request.body
            if not body:
                return []
            root = ET.fromstring(body)
            # 检查是否是 <allprop/>
            for elem in root.iter():
                if elem.tag == f"{{{DAV_NS}}}allprop":
                    return []
                if elem.tag == f"{{{DAV_NS}}}propname":
                    return ["propname"]
            # 提取 <prop> 中的属性
            prop_elem = root.find(f"{{{DAV_NS}}}prop")
            if prop_elem is not None:
                return [child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        for child in prop_elem]
            return []
        except Exception:
            return []

    def _build_propstat_response(
        self, path: str, item: Any, requested_props: List[str]
    ) -> Element:
        """
        为单个文件/目录构建 DAV:response 元素。
        """
        from datetime import datetime, timezone

        response = Element(f"{{{DAV_NS}}}response")

        # href
        href = SubElement(response, f"{{{DAV_NS}}}href")
        # 确保 URL 编码正确
        encoded_path = path.encode("utf-8") if isinstance(path, str) else path
        href.text = encoded_path.decode("utf-8") if isinstance(encoded_path, bytes) else str(path)

        # propstat
        propstat = SubElement(response, f"{{{DAV_NS}}}propstat")
        prop = SubElement(propstat, f"{{{DAV_NS}}}prop")

        # 决定要返回哪些属性
        is_allprop = not requested_props or "propname" in requested_props
        props_to_return = requested_props if not is_allprop else []

        prop_definitions = {
            "creationdate": lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(item.modify_time or time.time())),
            "displayname": lambda: item.name or "",
            "getlastmodified": lambda: (
                time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(item.modify_time or time.time()))
                if item.modify_time else ""
            ),
            "getlastmodified_2": lambda: (
                datetime.fromtimestamp(item.modify_time or time.time(), tz=timezone.utc).isoformat()
                if item.modify_time else ""
            ),
            "getetag": lambda: f'"{hash(str(item.path) + str(item.modify_time))}"',
            "getcontentlength": lambda: str(item.size or 0) if item.type == "file" else None,
            "getcontenttype": lambda: self._guess_content_type(item),
            "resourcetype": lambda: self._build_resource_type(item),
            "iscollection": lambda: ("true" if item.type == "dir" else "false"),
            "supportedlock": lambda: None,
            "lockdiscovery": lambda: None,
        }

        if is_allprops := (is_allprop or not props_to_return):
            # 返回所有标准属性
            for prop_name, value_fn in prop_definitions.items():
                if prop_name.endswith("_2"):
                    continue
                try:
                    value = value_fn()
                    if value is not None:
                        elem = SubElement(prop, f"{{{DAV_NS}}}{prop_name}")
                        if isinstance(value, Element):
                            elem.append(value)
                        elif value:
                            elem.text = str(value)
                except Exception:
                    pass
        else:
            # 只返回请求的属性
            for prop_name in props_to_return:
                fn = prop_definitions.get(prop_name)
                if fn:
                    try:
                        value = fn()
                        if value is not None:
                            elem = SubElement(prop, f"{{{DAV_NS}}}{prop_name}")
                            if isinstance(value, Element):
                                elem.append(value)
                            elif value:
                                elem.text = str(value)
                    except Exception:
                        pass

        status = SubElement(propstat, f"{{{DAV_NS}}}status")
        status.text = "HTTP/1.1 200 OK"

        return response

    @staticmethod
    def _build_resource_type(item: Any) -> Optional[Element]:
        """构建 resourcetype 元素。"""
        if item.type == "dir":
            collection = Element(f"{{{DAV_NS}}}collection")
            return collection
        return None  # 文件不添加子元素

    @staticmethod
    def _guess_content_type(item: Any) -> Optional[str]:
        """根据扩展名猜测 Content-Type。"""
        if item.type != "file" or not item.extension:
            return None

        ext_map = {
            "mp4": "video/mp4",
            "mkv": "video/x-matroska",
            "avi": "video/x-msvideo",
            "mov": "video/quicktime",
            "wmv": "video/x-ms-wmv",
            "flv": "video/x-flv",
            "webm": "video/webm",
            "ts": "video/mp2t",
            "m2ts": "video/mp2t",
            "mp3": "audio/mpeg",
            "flac": "audio/flac",
            "wav": "audio/wav",
            "aac": "audio/aac",
            "ogg": "audio/ogg",
            "m4a": "audio/mp4",
            "srt": "text/plain",
            "ass": "text/plain",
            "ssa": "text/plain",
            "sub": "text/plain",
            "idx": "text/plain",
            "smi": "text/plain",
            "nfo": "text/xml",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
            "iso": "application/x-iso9660-image",
            "zip": "application/zip",
            "rar": "application/vnd.rar",
            "7z": "application/x-7z-compressed",
        }
        return ext_map.get(item.extension.lower(), "application/octet-stream")

    @staticmethod
    def _prettify_xml(xml_str: str) -> str:
        """简单格式化 XML（保持兼容性）。"""
        try:
            try:
                root = ET.fromstring(xml_str)
                ET.indent(root, space="  ")
                return ET.tostring(root, encoding="unicode")
            except (LookupError, TypeError):
                # Python < 3.9 不支持 indent，返回原始
                return xml_str
        except Exception:
            return xml_str

    # ------------------------------------------------------------------
    # GET / HEAD — 流式下载/播放
    # ------------------------------------------------------------------
    def _handle_get(self, request: Request, path: str) -> Response:
        """GET 下载/流式播放文件。"""
        import requests as http_requests
        from pathlib import Path as PathLib

        item = self._api.get_item(PathLib(path))
        if not item:
            return Response(status_code=404)
        if item.type != "file":
            return Response(status_code=403, content="Cannot GET a directory")

        logger.info(f"【光鸭云盘助手】【WebDAV】GET file: {path}, name={item.name}, size={item.size}")

        # 获取签名下载 URL
        dl_response = self._client.get_download_url(item.fileid)
        if dl_response.get("msg") != "success" and dl_response.get("code") != 0:
            return Response(
                status_code=502,
                content=f"Failed to get download URL: {dl_response.get('msg', 'unknown')}",
            )

        data = dl_response.get("data", {}) or {}
        download_url = data.get("signedURL") or data.get("downloadUrl")
        if not download_url:
            return Response(status_code=502, content="No download URL available")

        # 转发头
        forward_headers = {
            "User-Agent": request.headers.get("user-agent", "Mozilla/5.0 (WebDAV/1 GuangyaDisk)"),
            "Referer": "https://www.guangyupan.com/",
        }
        range_header = request.headers.get("range")
        if range_header:
            forward_headers["Range"] = range_header

        req = http_requests.get(
            download_url,
            headers=forward_headers,
            stream=True,
            timeout=300,
            allow_redirects=True,
        )

        if req.status_code >= 400:
            error_msg = f"Upstream error: HTTP {req.status_code}"
            logger.error(f"【光鸭云盘助手】【WebDAV】{error_msg}")
            return Response(status_code=req.status_code, content=error_msg)

        # 构建响应头
        response_headers = {
            "Content-Type": req.headers.get("content-type", self._guess_content_type(item) or "application/octet-stream"),
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Duration": "",
        }
        content_length = req.headers.get("content-length")
        if content_length:
            response_headers["Content-Length"] = content_length
        content_range = req.headers.get("content-range")
        if content_range:
            response_headers["Content-Range"] = content_range
        response_headers["Content-Disposition"] = f'inline; filename="{item.name}"'

        def generate():
            try:
                for chunk in req.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        yield chunk
            except Exception as e:
                logger.warning(f"【光鸭云盘助手】【WebDAV】Stream interrupted: {e}")
            finally:
                req.close()

        status_code = req.status_code if range_header else 200
        return StreamingResponse(
            generate(),
            status_code=status_code,
            headers=response_headers,
        )

    def _handle_head(self, request: Request, path: str) -> Response:
        """HEAD 获取文件元信息（不返回 body）。"""
        from pathlib import Path as PathLib

        item = self._api.get_item(PathLib(path))
        if not item:
            return Response(status_code=404)
        if item.type != "file":
            return Response(status_code=403)

        content_type = self._guess_content_type(item) or "application/octet-stream"
        headers = {
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Content-Length": str(item.size or 0),
            "Cache-Control": "public, max-age=3600",
            "Last-Modified": time.strftime(
                "%a, %d %b %Y %H:%M:%S GMT",
                time.gmtime(item.modify_time or time.time()),
            ),
        }
        return Response(headers=headers)

    # ------------------------------------------------------------------
    # MKCOL — 创建目录
    # ------------------------------------------------------------------
    def _handle_mkcol(self, request: Request, path: str) -> Response:
        """创建集合（目录）。"""
        from pathlib import Path as PathLib

        parent_path = str(PathLib(path).parent).replace("\\", "/") or "/"
        dir_name = PathLib(path).name

        parent_item = self._api.get_item(PathLib(parent_path))
        if not parent_item:
            return Response(status_code=409, content="Parent not found")

        result = self._api.create_folder(parent_item, dir_name)
        if result:
            return Response(status_code=201)  # Created
        return Response(status_code=405, content="Cannot create folder")

    # ------------------------------------------------------------------
    # DELETE — 删除
    # ------------------------------------------------------------------
    def _handle_delete(self, request: Request, path: str) -> Response:
        """删除资源。"""
        from pathlib import Path as PathLib

        item = self._api.get_item(PathLib(path))
        if not item:
            return Response(status_code=404)

        result = self._api.delete(item)
        if result:
            return Response(status_code=204)  # No Content
        return Response(status_code=500, content="Delete failed")

    # ------------------------------------------------------------------
    # PUT — 上传
    # ------------------------------------------------------------------
    def _handle_put(self, request: Request, path: str) -> Response:
        """上传/创建文件。"""
        from pathlib import Path as PathLib
        import tempfile

        parent_path = str(PathLib(path).parent).replace("\\", "/") or "/"
        file_name = PathLib(path).name

        parent_item = self._api.get_item(PathLib(parent_path))
        if not parent_item:
            return Response(status_code=409, content="Parent not found")

        # PUT 响应区分新建(201)与覆盖(204)，并避免旧实现引用未定义的 item。
        existing_item = self._api.get_item(PathLib(path))

        # 将上传内容写入临时文件（同步环境下从 _body 缓存读取）
        body = getattr(request, '_body', None) or b""
        if not body:
            return Response(status_code=400, content="Empty body")

        with tempfile.NamedTemporaryFile(suffix=f"_{file_name}", delete=False, mode="wb") as tmp:
            tmp.write(body)
            tmp_path = tmp.name

        try:
            local_path = PathLib(tmp_path)
            result = self._api.upload(parent_item, local_path, new_name=file_name)
            if result:
                return Response(status_code=201 if not existing_item else 204)
            return Response(status_code=500, content="Upload failed")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # MOVE — 移动/重命名
    # ------------------------------------------------------------------
    def _handle_move(self, request: Request, path: str) -> Response:
        """移动资源。"""
        destination = request.headers.get("destination", "")
        if not destination:
            return Response(status_code=400, content="Missing Destination header")

        from pathlib import Path as PathLib
        from urllib.parse import urlparse

        parsed = urlparse(destination)
        dest_path = parsed.path.replace("\\", "/").rstrip("/") or "/"

        item = self._api.get_item(PathLib(path))
        if not item:
            return Response(status_code=404)

        target_parent = str(PathLib(dest_path).parent).replace("\\", "/") or "/"
        new_name = PathLib(dest_path).name

        result = self._api.move(item, PathLib(target_parent), new_name=new_name)
        if result:
            return Response(status_code=201)
        return Response(status_code=500, content="Move failed")

    # ------------------------------------------------------------------
    # COPY — 复制
    # ------------------------------------------------------------------
    def _handle_copy(self, request: Request, path: str) -> Response:
        """复制资源。"""
        destination = request.headers.get("destination", "")
        if not destination:
            return Response(status_code=400, content="Missing Destination header")

        from pathlib import Path as PathLib
        from urllib.parse import urlparse

        parsed = urlparse(destination)
        dest_path = parsed.path.replace("\\", "/").rstrip("/") or "/"

        item = self._api.get_item(PathLib(path))
        if not item:
            return Response(status_code=404)

        target_parent = str(PathLib(dest_path).parent).replace("\\", "/") or "/"
        new_name = PathLib(dest_path).name

        result = self._api.copy(item, PathLib(target_parent), new_name=new_name)
        if result:
            return Response(status_code=201)
        return Response(status_code=500, content="Copy failed")

# =============================================================================
# API models
# =============================================================================

"""MoviePilot V3 API response models for GuangYaDisk."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GuangYaConfigData(BaseModel):
    """Configuration/status payload consumed by the Vue remote component."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    device_id: str = ""
    poll_interval: int = 5
    page_size: int = 100
    order_by: int = 3
    sort_type: int = 1
    permanently_delete: bool = False
    upload_progress_log: bool = False
    logged_in: bool = False
    storage_name: str = "光鸭云盘助手"
    remote_status_available: bool = True
    remote_status_message: str = ""
    user_name: str = ""
    user_id: str = ""
    vip_level: str = ""
    member_expire_time: int = 0
    total_space: int = 0
    used_space: int = 0
    free_space: int = 0
    file_count: int = 0
    user_code: str = ""
    verification_uri: str = ""
    qr_expires_in: int = 0


class GuangYaConfigSaveResponse(BaseModel):
    """Config save response. Kept as the existing three-field envelope."""

    success: bool
    message: str = ""
    data: Optional[GuangYaConfigData] = None


class GuangYaActionResponse(BaseModel):
    """Flexible login/logout response while retaining a documented stable core."""

    model_config = ConfigDict(extra="allow")

    success: bool
    message: str = ""
    waiting: Optional[bool] = None
    stage: str = ""
    enabled: Optional[bool] = None
    device_id: str = ""
    user_code: str = ""
    verification_uri: str = ""
    verification_uri_complete: str = ""
    expires_in: int = 0
    has_access_token: Optional[bool] = None
    has_refresh_token: Optional[bool] = None
    phone_number: str = ""
    verification_id: str = ""
    captcha_token: str = ""


class GuangYaBrowseItem(BaseModel):
    """One file/directory returned by the browse endpoint."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    path: str
    size: int = 0
    extension: str = ""
    modify_time: int = 0
    stream_url: Optional[str] = None


class GuangYaBrowseResponse(BaseModel):
    """Directory browse response."""

    model_config = ConfigDict(extra="allow")

    path: str = "/"
    name: str = ""
    type: str = "dir"
    items: List[GuangYaBrowseItem] = Field(default_factory=list)
    stream_base: str = ""
    browse_base: str = ""
    total_files: int = 0
    total_dirs: int = 0
    error: str = ""


class GuangYaOrganizerResponse(BaseModel):
    """网盘整理统一响应：data 内承载策略、目录、预览计划、执行结果或历史。"""

    model_config = ConfigDict(extra="allow")

    success: bool
    message: str = ""
    data: Optional[Dict[str, Any]] = None

# =============================================================================
# Legacy storage/plugin behavior (flattened)
# =============================================================================

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import os
import time
import uuid

from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from app import schemas
from app.sdk.events import Event, eventmanager
from app.sdk.services import StorageHelper
from app.sdk.logging import logger
from app.plugins import _PluginBase
from app.schemas.workflow import FileItem
from app.schemas.event import StorageOperSelectionEventData
from app.schemas.types import ChainEventType

class _LegacyShukGuangYaDisk(_PluginBase):
    # 插件名称
    plugin_name = "光鸭云盘助手"
    # 插件描述
    plugin_desc = "将光鸭云盘挂载为 MoviePilot / Emby 存储介质，支持扫码登录、文件浏览、上传下载、Emby 媒体库直连。"
    # 插件图标 - 使用内建默认图标
    plugin_icon = "Guangyadisk_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "liheng-lk"
    # 作者主页
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"
    # 插件配置项 ID 前缀
    plugin_config_prefix = "shuk_guangyadisk_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _disk_name = "光鸭云盘助手"
    _client: Optional[GuangYaClient] = None
    _guangya_api: Optional[GuangYaApi] = None

    _access_token: str = ""
    _refresh_token: str = ""
    _client_id: str = GuangYaClient.DEFAULT_CLIENT_ID
    _device_id: str = ""
    _device_code: str = ""
    _poll_interval: int = 5
    _page_size: int = 100
    _order_by: int = 3
    _sort_type: int = 1
    _permanently_delete: bool = False
    _user_code: str = ""
    _verification_uri: str = ""
    _qr_expires_at: float = 0

    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)

    @staticmethod
    def _mask_token(token: str, keep: int = 10) -> str:
        """
        脱敏显示 token。
        """
        if not token:
            return ""
        token = str(token)
        if len(token) <= keep * 2:
            return token
        return f"{token[:keep]}...{token[-keep:]}"

    def __init__(self):
        """
        初始化插件。
        """
        super().__init__()

    def _clear_auth_state(self, reason: str = ""):
        """
        清理认证状态并持久化。
        """
        if reason:
            logger.warning(f"【光鸭云盘助手】清理登录状态: {reason}")
        self._access_token = ""
        self._refresh_token = ""
        self._device_code = ""
        self._user_code = ""
        self._verification_uri = ""
        self._qr_expires_at = 0
        if self._client:
            self._client._access_token = ""
            self._client._refresh_token = ""
        self.update_config(
            {
                "enabled": self._enabled,
                "access_token": "",
                "refresh_token": "",
                "client_id": self._client_id,
                "device_id": self._device_id,
                "poll_interval": self._poll_interval,
                "page_size": self._page_size,
                "order_by": self._order_by,
                "sort_type": self._sort_type,
                "permanently_delete": self._permanently_delete,
            }
        )

    def init_plugin(self, config: dict = None):
        """
        初始化插件。
        """
        config = config or {}

        storage_helper = StorageHelper()
        storages = storage_helper.get_storagies()
        if not any(
            s.type == self._disk_name and s.name == self._disk_name for s in storages
        ):
            storage_helper.add_storage(
                storage=self._disk_name,
                name=self._disk_name,
                conf={},
            )

        self._enabled = bool(config.get("enabled"))
        self._access_token = (config.get("access_token") or "").strip()
        self._refresh_token = (config.get("refresh_token") or "").strip()
        self._client_id = (
            (config.get("client_id") or GuangYaClient.DEFAULT_CLIENT_ID).strip()
            or GuangYaClient.DEFAULT_CLIENT_ID
        )
        self._device_id = (config.get("device_id") or "").strip()
        self._page_size = int(config.get("page_size") or 100)
        self._order_by = int(config.get("order_by") or 3)
        self._sort_type = int(config.get("sort_type") or 1)
        self._poll_interval = int(config.get("poll_interval") or 5)
        self._permanently_delete = bool(config.get("permanently_delete"))

        logger.info("【光鸭云盘助手】初始化插件: enabled=%s, device_id=%s, authenticated=%s", self._enabled, self._device_id, bool(self._access_token))

        def on_token_refresh(access_token: str, refresh_token: str):
            """
            token 刷新后自动持久化。
            """
            logger.info("【光鸭云盘助手】Token 已刷新并持久化")
            self._access_token = access_token
            self._refresh_token = refresh_token
            config_payload = {
                "enabled": self._enabled,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "device_id": self._device_id,
                "poll_interval": self._poll_interval,
                "page_size": self._page_size,
                "order_by": self._order_by,
                "sort_type": self._sort_type,
                "permanently_delete": self._permanently_delete,
            }
            logger.info("【光鸭云盘助手】准备回写认证配置: device_id=%s", self._device_id)
            self.update_config(config_payload)
            logger.info("【光鸭云盘助手】Token 已自动保存")

        try:
            self._client = GuangYaClient(
                access_token=self._access_token,
                refresh_token=self._refresh_token,
                client_id=self._client_id,
                device_id=self._device_id,
                on_token_refresh=on_token_refresh,
            )
            self._device_id = self._client.device_id
            self._guangya_api = GuangYaApi(
                client=self._client,
                disk_name=self._disk_name,
                page_size=self._page_size,
                order_by=self._order_by,
                sort_type=self._sort_type,
                permanently_delete=self._permanently_delete,
            )
        except Exception as err:
            logger.error(f"光鸭云盘助手客户端创建失败: {err}")
            self._client = None
            self._guangya_api = None

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_render_mode(self) -> Tuple[str, Optional[str]]:
        """
        返回 Vue 渲染模式。
        """
        return "vue", "dist/assets"

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件 API 端点。
        """
        return [
            {
                "path": "/config",
                "endpoint": self._get_config,
                "auth": "bear",
                "methods": ["GET"],
                "summary": "获取配置",
            },
            {
                "path": "/config",
                "endpoint": self._save_config,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "保存配置",
            },
            {
                "path": "/login/qrcode",
                "endpoint": self.get_qrcode,
                "auth": "bear",
                "methods": ["GET"],
                "summary": "获取扫码登录二维码",
            },
            {
                "path": "/login/poll",
                "endpoint": self.poll_login,
                "auth": "bear",
                "methods": ["GET"],
                "summary": "轮询扫码登录状态",
            },
            {
                "path": "/login/logout",
                "endpoint": self.logout,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "退出登录",
            },
            {
                "path": "/stream",
                "endpoint": self.stream_file,
                "auth": "bear",
                "methods": ["GET"],
                "summary": "流式代理网盘文件（供 Emby/播放器直连）",
            },
            {
                "path": "/browse",
                "endpoint": self.browse_path,
                "auth": "bear",
                "methods": ["GET"],
                "summary": "浏览网盘目录（返回 JSON 目录结构）",
            },
            {
                "path": "/webdav",
                "endpoint": self.webdav,
                "auth": "bear",
                "methods": ["OPTIONS", "PROPFIND", "GET", "HEAD", "MKCOL", "DELETE", "PUT", "MOVE", "COPY"],
                "summary": "WebDAV 服务端（Emby/Jellyfin 可通过 WebDAV 挂载光鸭云盘为媒体库）",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        Vue 模式下返回空表单与初始配置。
        """
        return None, {
            "enabled": False,
            "access_token": "",
            "refresh_token": "",
            "client_id": GuangYaClient.DEFAULT_CLIENT_ID,
            "device_id": "",
            "poll_interval": 5,
            "page_size": 100,
            "order_by": 3,
            "sort_type": 1,
            "permanently_delete": False,
        }

    def get_page(self) -> List[dict]:
        """
        Vue 模式下返回空页面。
        """
        return []

    def _get_config(self) -> Dict[str, Any]:
        """
        获取当前配置。
        """
        def _pick_first(data: Dict[str, Any], *keys: str) -> Any:
            for key in keys:
                value = data.get(key)
                if value not in (None, ""):
                    return value
            return None

        def _to_int(value: Any) -> int:
            if value in (None, ""):
                return 0
            try:
                return int(value)
            except (TypeError, ValueError):
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return 0

        def _is_auth_invalid(result: Dict[str, Any]) -> bool:
            if not isinstance(result, dict):
                return False
            error_text = str(result.get("error") or "")
            msg_text = str(result.get("msg") or "")
            detail_text = str(result)
            return any(
                keyword in f"{error_text} {msg_text} {detail_text}"
                for keyword in ["unauthenticated", "无效token", "Authorize failed", "认证失败"]
            )

        def _should_clear_auth(result: Dict[str, Any]) -> bool:
            if not _is_auth_invalid(result):
                return False
            if not self._client:
                return False
            return bool(self._client.last_refresh_attempted and self._client.last_refresh_invalid)

        config = {
            "enabled": self._enabled,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "client_id": self._client_id or GuangYaClient.DEFAULT_CLIENT_ID,
            "device_id": self._device_id,
            "poll_interval": self._poll_interval,
            "page_size": self._page_size,
            "order_by": self._order_by,
            "sort_type": self._sort_type,
            "permanently_delete": self._permanently_delete,
            "logged_in": False,
            "user_code": self._user_code,
            "verification_uri": self._verification_uri,
            "qr_expires_in": max(int(self._qr_expires_at - time.time()), 0) if self._qr_expires_at else 0,
        }
        
        # 如果已登录，尝试获取用户信息和空间统计
        if self._access_token and self._client:
            try:
                # 获取用户信息
                user_info = self._client.get_user_info() or {}
                if _should_clear_auth(user_info):
                    self._clear_auth_state(
                        f"access_token/refresh_token 已失效，需要重新扫码登录: {self._client.last_refresh_result}"
                    )
                    config["access_token"] = ""
                    config["refresh_token"] = ""
                    config["device_id"] = self._device_id
                    config["user_name"] = ""
                    config["user_id"] = ""
                    config["vip_level"] = ""
                    config["member_expire_time"] = 0
                    config["total_space"] = 0
                    config["used_space"] = 0
                    config["free_space"] = 0
                    config["file_count"] = 0
                    return config
                if _is_auth_invalid(user_info):
                    logger.warning(f"【光鸭云盘助手】用户信息接口认证异常，但未确认 refresh_token 失效，暂不清空登录态: {user_info}")
                    config["user_name"] = ""
                    config["user_id"] = ""
                    config["vip_level"] = ""
                    config["member_expire_time"] = 0
                    config["total_space"] = 0
                    config["used_space"] = 0
                    config["free_space"] = 0
                    config["file_count"] = 0
                    return config

                user_data = user_info.get("data") if isinstance(user_info.get("data"), dict) else user_info
                user_name = _pick_first(
                    user_data,
                    "name",
                    "user_name",
                    "username",
                    "nickname",
                    "nickName",
                    "phone",
                    "mobile",
                    "display_name",
                    "preferred_username",
                )
                user_id = _pick_first(
                    user_data,
                    "user_id",
                    "userId",
                    "id",
                    "sub",
                    "uid",
                    "openId",
                )
                vip_level = _pick_first(
                    user_data,
                    "vip_level",
                    "vipLevel",
                    "vip",
                    "level",
                    "memberLevel",
                    "vipName",
                    "memberType",
                )

                if user_name is None and user_id is not None:
                    user_name = user_id

                if user_name is None and user_id is None:
                    logger.warning(f"【光鸭云盘助手】用户信息无有效身份字段，视为未登录: {user_info}")
                    config["user_name"] = ""
                    config["user_id"] = ""
                    config["vip_level"] = ""
                    config["member_expire_time"] = 0
                    config["total_space"] = 0
                    config["used_space"] = 0
                    config["free_space"] = 0
                    config["file_count"] = 0
                    return config

                config["user_name"] = "" if user_name is None else str(user_name)
                config["user_id"] = "" if user_id is None else str(user_id)
                config["vip_level"] = "" if vip_level is None else str(vip_level)
                config["member_expire_time"] = 0
                config["logged_in"] = True
                
                # 获取空间统计
                assets_info = self._client.get_assets() or {}
                if _should_clear_auth(assets_info):
                    self._clear_auth_state(
                        f"空间信息接口返回未认证，且 refresh_token 已失效，需要重新扫码登录: {self._client.last_refresh_result}"
                    )
                    config["logged_in"] = False
                    config["access_token"] = ""
                    config["refresh_token"] = ""
                    config["user_name"] = ""
                    config["user_id"] = ""
                    config["vip_level"] = ""
                    config["member_expire_time"] = 0
                    config["total_space"] = 0
                    config["used_space"] = 0
                    config["free_space"] = 0
                    config["file_count"] = 0
                    return config
                if _is_auth_invalid(assets_info):
                    logger.warning(f"【光鸭云盘助手】空间信息接口认证异常，但未确认 refresh_token 失效，暂不清空登录态: {assets_info}")
                    config["total_space"] = 0
                    config["used_space"] = 0
                    config["free_space"] = 0
                    config["file_count"] = 0
                    return config

                assets_data = assets_info.get("data") if isinstance(assets_info.get("data"), dict) else assets_info
                total_space = _to_int(
                    _pick_first(
                        assets_data,
                        "totalSpaceSize",
                        "total_space",
                        "totalSpace",
                        "total",
                    )
                )
                used_space_raw = _pick_first(
                    assets_data,
                    "usedSpaceSize",
                    "used_space",
                    "usedSpace",
                    "used",
                )
                used_space = _to_int(used_space_raw)
                free_space_raw = _pick_first(
                    assets_data,
                    "freeSpaceSize",
                    "free_space",
                    "freeSpace",
                    "free",
                    "available",
                )
                free_space = _to_int(free_space_raw)
                if free_space == 0 and total_space and used_space_raw not in (None, ""):
                    free_space = max(total_space - used_space, 0)

                config["total_space"] = total_space
                config["used_space"] = used_space
                config["free_space"] = free_space
                config["file_count"] = _to_int(
                    _pick_first(assets_data, "file_count", "fileCount", "totalFileCount")
                )
                config["member_expire_time"] = _to_int(
                    _pick_first(assets_data, "vipExpireTime", "vip_expire_time", "expireTime")
                )
            except Exception as err:
                logger.error(f"【光鸭云盘助手】获取用户信息失败: {err}")
                config["logged_in"] = False
                config["user_name"] = ""
                config["user_id"] = ""
                config["vip_level"] = ""
                config["member_expire_time"] = 0
                config["total_space"] = 0
                config["used_space"] = 0
                config["free_space"] = 0
                config["file_count"] = 0
        else:
            config["user_name"] = ""
            config["user_id"] = ""
            config["vip_level"] = ""
            config["member_expire_time"] = 0
            config["total_space"] = 0
            config["used_space"] = 0
            config["free_space"] = 0
            config["file_count"] = 0
        
        return config

    def _save_config(self, config_payload: dict) -> Dict[str, Any]:
        """
        保存插件配置。
        """
        try:
            config_payload = config_payload or {}
            new_config = {
                "enabled": bool(config_payload.get("enabled", self._enabled)),
                "access_token": (config_payload.get("access_token") or self._access_token or "").strip(),
                "refresh_token": (config_payload.get("refresh_token") or self._refresh_token or "").strip(),
                "client_id": (
                    (config_payload.get("client_id") or self._client_id or GuangYaClient.DEFAULT_CLIENT_ID).strip()
                    or GuangYaClient.DEFAULT_CLIENT_ID
                ),
                "device_id": (config_payload.get("device_id") or self._device_id or "").strip(),
                "poll_interval": int(config_payload.get("poll_interval") or self._poll_interval or 5),
                "page_size": int(config_payload.get("page_size") or self._page_size or 100),
                "order_by": int(config_payload.get("order_by") or self._order_by or 3),
                "sort_type": int(config_payload.get("sort_type") or self._sort_type or 1),
                "permanently_delete": bool(config_payload.get("permanently_delete", self._permanently_delete)),
            }
            self.update_config(new_config)
            self.init_plugin(new_config)
            return {
                "success": True,
                "message": "配置保存成功",
                "data": self._get_config(),
            }
        except Exception as err:
            logger.error(f"【光鸭云盘助手】保存配置失败: {err}")
            return {
                "success": False,
                "message": f"保存配置失败: {err}",
            }

    def get_module(self) -> Dict[str, Any]:
        """
        获取插件模块声明。
        """
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
        }

    @eventmanager.register(ChainEventType.StorageOperSelection)
    def storage_oper_selection(self, event: Event):
        """
        监听存储选择事件。
        """
        if not self._enabled:
            return
        event_data: StorageOperSelectionEventData = event.event_data
        if event_data.storage == self._disk_name:
            event_data.storage_oper = self._guangya_api  # noqa: SLF001

    def list_files(
        self, fileitem: schemas.FileItem, recursion: bool = False
    ) -> Optional[List[schemas.FileItem]]:
        """
        查询目录下所有目录和文件。
        """
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return []

        result: List[schemas.FileItem] = []

        def _walk(_item: FileItem, _recursion: bool = False):
            items = self._guangya_api.list(_item)
            if not items:
                return
            if _recursion:
                for sub_item in items:
                    if sub_item.type == "dir":
                        _walk(sub_item, _recursion)
                    else:
                        result.append(sub_item)
            else:
                result.extend(items)

        _walk(fileitem, recursion)
        return result

    def any_files(
        self, fileitem: schemas.FileItem, extensions: list = None
    ) -> Optional[bool]:
        """
        查询目录下是否存在任意目标文件。
        """
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return False

        def _any(_item: FileItem) -> bool:
            items = self._guangya_api.list(_item)
            if not items:
                return False
            if not extensions:
                return True
            for sub_item in items:
                if (
                    sub_item.type == "file"
                    and sub_item.extension
                    and f".{sub_item.extension.lower()}" in extensions
                ):
                    return True
                if sub_item.type == "dir" and _any(sub_item):
                    return True
            return False

        return _any(fileitem)

    def create_folder(
        self, fileitem: schemas.FileItem, name: str
    ) -> Optional[schemas.FileItem]:
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.create_folder(fileitem=fileitem, name=name)

    def download_file(
        self, fileitem: schemas.FileItem, path: Path = None
    ) -> Optional[Path]:
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.download(fileitem, path)

    def upload_file(
        self, fileitem: schemas.FileItem, path: Path, new_name: Optional[str] = None
    ) -> Optional[schemas.FileItem]:
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.upload(fileitem, path, new_name)

    def delete_file(self, fileitem: schemas.FileItem) -> Optional[bool]:
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.delete(fileitem)

    def rename_file(self, fileitem: schemas.FileItem, name: str) -> Optional[bool]:
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.rename(fileitem, name)

    def exists(self, fileitem: schemas.FileItem) -> Optional[bool]:
        if fileitem.storage != self._disk_name:
            return None
        return True if self.get_item(fileitem) else False

    def get_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        if fileitem.storage != self._disk_name:
            return None
        return self.get_file_item(storage=fileitem.storage, path=Path(fileitem.path))

    def get_file_item(self, storage: str, path: Path) -> Optional[schemas.FileItem]:
        if storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.get_item(path)

    def get_parent_item(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        if fileitem.storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.get_parent(fileitem)

    def snapshot_storage(
        self,
        storage: str,
        path: Path,
        last_snapshot_time: float = None,
        max_depth: int = 5,
    ) -> Optional[Dict[str, Dict]]:
        if storage != self._disk_name:
            return None
        if not self._guangya_api:
            return {}

        files_info: Dict[str, Dict] = {}

        def _snapshot(_fileitem: schemas.FileItem, current_depth: int = 0):
            try:
                if _fileitem.type == "dir":
                    if current_depth >= max_depth:
                        return
                    if (
                        self.snapshot_check_folder_modtime  # noqa
                        and last_snapshot_time
                        and _fileitem.modify_time
                        and _fileitem.modify_time <= last_snapshot_time
                    ):
                        return
                    for sub_file in self._guangya_api.list(_fileitem):
                        _snapshot(sub_file, current_depth + 1)
                else:
                    modify_time = getattr(_fileitem, "modify_time", 0) or 0
                    if not last_snapshot_time or modify_time > last_snapshot_time:
                        files_info[_fileitem.path] = {
                            "size": _fileitem.size or 0,
                            "modify_time": modify_time,
                            "type": _fileitem.type,
                        }
            except Exception as err:
                logger.debug(f"Snapshot error for {_fileitem.path}: {err}")

        root_item = self._guangya_api.get_item(path)
        if not root_item:
            return {}
        _snapshot(root_item)
        return files_info

    def storage_usage(self, storage: str) -> Optional[schemas.StorageUsage]:
        if storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.usage()

    def support_transtype(self, storage: str) -> Optional[dict]:
        if storage != self._disk_name:
            return None
        return {"move": "移动", "copy": "复制"}

    def get_qrcode(self) -> Dict[str, Any]:
        """
        获取扫码二维码。
        """
        try:
            self._device_id = uuid.uuid4().hex
            self._qr_expires_at = 0
            temp_client = GuangYaClient(
                access_token=None,
                refresh_token=None,
                client_id=self._client_id,
                device_id=self._device_id,
            )
            result = temp_client.get_device_code() or {}
            device_code = str(result.get("device_code") or "").strip()
            if result.get("error") or not device_code:
                message = (
                    result.get("error_description")
                    or result.get("message")
                    or result.get("msg")
                    or result.get("error")
                    or "光鸭设备码接口未返回 device_code"
                )
                logger.warning("【光鸭云盘助手】【登录】二维码设备码获取失败: %s", message)
                return {
                    "success": False,
                    "message": f"二维码登录暂不可用：{message}",
                    "stage": "device_code_error",
                    "qr_available": False,
                    "login_alternatives": ["sms", "token"],
                    "upstream": result,
                }

            self._device_code = device_code
            self._poll_interval = int(result.get("interval") or self._poll_interval or 5)
            self._user_code = str(result.get("user_code") or "").strip()
            verification_complete = str(result.get("verification_uri_complete") or "").strip()
            self._verification_uri = str(result.get("verification_uri") or verification_complete or "").strip()
            expires_in = int(result.get("expires_in") or 300)
            self._qr_expires_at = time.time() + expires_in

            return {
                "success": True,
                "user_code": self._user_code,
                "verification_uri": self._verification_uri,
                "verification_uri_complete": verification_complete,
                "expires_in": expires_in,
                "device_id": self._device_id,
                "qr_available": True,
            }
        except Exception as err:
            logger.error(f"【光鸭云盘助手】获取二维码失败: {err}")
            return {"success": False, "message": f"获取二维码失败: {err}"}

    def poll_login(self) -> Dict[str, Any]:
        """
        轮询扫码登录状态。
        """
        if not self._device_code:
            return {"success": False, "message": "请先获取二维码"}
        if self._qr_expires_at and time.time() > self._qr_expires_at:
            return {"success": False, "message": "二维码已过期，请重新获取"}

        try:
            temp_client = GuangYaClient(
                access_token=None,
                refresh_token=None,
                client_id=self._client_id,
                device_id=self._device_id,
            )
            result = temp_client.poll_device_code(self._device_code) or {}
            if result.get("waiting"):
                return {"success": False, "message": result.get("message") or "等待扫码中...", "waiting": True, "stage": result.get("stage") or "authorization_pending"}
            if not result.get("access_token"):
                stage = str(result.get("stage") or "device_token_error")
                message = str(result.get("message") or result.get("error_description") or result.get("error") or "光鸭未返回登录令牌")
                if str(result.get("error") or "") in {"expired_token", "access_denied", "invalid_grant"}:
                    self._device_code = ""
                    self._qr_expires_at = 0
                return {"success": False, "message": message, "waiting": False, "stage": stage, "upstream": result}

            self._access_token = result.get("access_token") or ""
            self._refresh_token = result.get("refresh_token") or ""
            self.update_config(
                {
                    "enabled": self._enabled,
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "device_id": self._device_id,
                    "poll_interval": self._poll_interval,
                    "page_size": self._page_size,
                    "order_by": self._order_by,
                    "sort_type": self._sort_type,
                    "permanently_delete": self._permanently_delete,
                }
            )
            self.init_plugin(
                {
                    "enabled": self._enabled,
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "device_id": self._device_id,
                    "poll_interval": self._poll_interval,
                    "page_size": self._page_size,
                    "order_by": self._order_by,
                    "sort_type": self._sort_type,
                    "permanently_delete": self._permanently_delete,
                }
            )
            self._device_code = ""
            logger.info("【光鸭云盘助手】扫码登录成功")
            return {
                "success": True,
                "message": "登录成功",
                "device_id": self._device_id,
            }
        except Exception as err:
            logger.error(f"【光鸭云盘助手】轮询登录失败: {err}")
            return {"success": False, "message": f"轮询失败: {err}"}

    def logout(self) -> Dict[str, Any]:
        """
        退出登录。
        """
        self._access_token = ""
        self._refresh_token = ""
        self._device_code = ""
        self._user_code = ""
        self._verification_uri = ""
        self._qr_expires_at = 0
        self._client = None
        self._guangya_api = None

        self.update_config(
            {
                "enabled": self._enabled,
                "access_token": "",
                "refresh_token": "",
                "client_id": self._client_id,
                "device_id": "",
                "poll_interval": self._poll_interval,
                "page_size": self._page_size,
                "order_by": self._order_by,
                "sort_type": self._sort_type,
                "permanently_delete": self._permanently_delete,
            }
        )
        return {"success": True, "message": "已退出登录"}

    def stream_file(self, request: Request, path: str = "") -> Response:
        """
        流式代理网盘文件，供 Emby / Jellyfin 等媒体服务器直连播放。
        
        用法: GET /plugin/shuk-guangyadisk/stream?path=/BMH/电影/xxx.mkv
        
        原理:
        1. 通过路径获取文件 item
        2. 调用光鸭 API 获取签名下载 URL (signedURL)
        3. 流式转发文件内容给客户端（支持 Range 请求/断点续传）
        """
        import requests as http_requests

        if not self._enabled or not self._client or not self._guangya_api:
            return Response(
                content='{"error": "插件未启用或未登录"}',
                status_code=503,
                media_type="application/json",
            )

        # 规范化路径
        normalized_path = str(path).replace("\\", "/").strip()
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        normalized_path = normalized_path.rstrip("/") or "/"
        if normalized_path == "/":
            return Response(
                content='{"error": "必须指定文件路径"}',
                status_code=400,
                media_type="application/json",
            )

        try:
            # 1. 通过路径获取文件 item
            file_item = self._guangya_api.get_item(Path(normalized_path))
            if not file_item:
                return Response(
                    content=f'{{"error": "文件不存在: {normalized_path}"}}',
                    status_code=404,
                    media_type="application/json",
                )
            if file_item.type != "file":
                return Response(
                    content=f'{{"error": "不是文件: {normalized_path}"}}',
                    status_code=400,
                    media_type="application/json",
                )

            logger.info(f"【光鸭云盘助手】流式代理请求: path={normalized_path}, name={file_item.name}, size={file_item.size}")

            # 2. 获取签名下载 URL
            dl_response = self._client.get_download_url(file_item.fileid)
            if dl_response.get("msg") != "success" and dl_response.get("code") != 0:
                return Response(
                    content=f'{{"error": "获取下载链接失败: {dl_response.get("msg", "unknown")}"}}',
                    status_code=502,
                    media_type="application/json",
                )
            
            data = dl_response.get("data", {}) or {}
            download_url = data.get("signedURL") or data.get("downloadUrl")
            if not download_url:
                return Response(
                    content='{"error": "无法获取下载 URL"}',
                    status_code=502,
                    media_type="application/json",
                )

            # 3. 构建转发的请求头（传递 Range 等关键头）
            forward_headers = {
                "User-Agent": (
                    request.headers.get("user-agent", 
                        "Mozilla/5.0 (compatible; Emby/1.0; GuangyaDiskProxy)")
                ),
                "Referer": "https://www.guangyupan.com/",
            }
            
            # 支持 Range 请求（Emby 播放必需）
            range_header = request.headers.get("range")
            if range_header:
                forward_headers["Range"] = range_header
            
            # 4. 流式代理
            req = http_requests.get(
                download_url,
                headers=forward_headers,
                stream=True,
                timeout=300,
                allow_redirects=True,
            )
            
            if req.status_code >= 400:
                error_msg = f"上游返回错误: HTTP {req.status_code}"
                logger.error(f"【光鸭云盘助手】{error_msg}")
                return Response(
                    content=f'{{"error": "{error_msg}"}}',
                    status_code=req.status_code,
                    media_type="application/json",
                )

            # 从上游响应构建响应头
            response_headers = {}
            content_type = req.headers.get("content-type", "video/mp4")
            response_headers["Content-Type"] = content_type
            
            content_length = req.headers.get("content-length")
            if content_length:
                response_headers["Content-Length"] = content_length
            
            # 传递 Content-Range 和 Accept-Ranges（支持 seeking）
            content_range = req.headers.get("content-range")
            if content_range:
                response_headers["Content-Range"] = content_range
            response_headers["Accept-Ranges"] = "bytes"
            
            # 缓存控制
            response_headers["Cache-Control"] = "public, max-age=3600"
            response_headers["X-Content-Duration"] = ""  # 让 Emby 自己探测时长

            # 文件名（用于浏览器直接访问时的下载提示）
            filename = file_item.name
            response_headers["Content-Disposition"] = f'inline; filename="{filename}"'

            def generate():
                """流式生成器：从光鸭云盘读取 chunk 并 yield 给客户端"""
                try:
                    for chunk in req.iter_content(chunk_size=1024 * 256):  # 256KB chunks
                        if chunk:
                            yield chunk
                except Exception as e:
                    logger.warning(f"【光鸭云盘助手】流式传输中断: {e}")
                finally:
                    req.close()

            status_code = req.status_code if range_header else 200
            return StreamingResponse(
                generate(),
                status_code=status_code,
                headers=response_headers,
                media_type=content_type,
            )

        except FileNotFoundError:
            return Response(
                content=f'{{"error": "文件不存在: {normalized_path}"}}',
                status_code=404,
                media_type="application/json",
            )
        except Exception as err:
            logger.error(f"【光鸭云盘助手】流式代理失败: {err}")
            return Response(
                content=f'{{"error": "{str(err)}"}}',
                status_code=500,
                media_type="application/json",
            )

    def browse_path(self, path: str = "/", recursion: bool = False) -> Dict[str, Any]:
        """
        浏览网盘目录结构，返回 JSON 格式的目录树。
        
        用法: GET /plugin/shuk-guangyadisk/browse?path=/BMH&recursion=false
        
        返回格式:
        {
            "path": "/BMH",
            "name": "BMH", 
            "items": [
                {"name": "电影", "type": "dir", "path": "/BMH/电影"},
                {"name": "xxx.mkv", "type": "file", "size": 1234567890, "path": "/BMH/xxx.mkv"}
            ],
            "stream_base": "/plugin/shuk-guangyadisk/stream"
        }
        """
        if not self._enabled or not self._guangya_api:
            return {"error": "插件未启用或未登录", "items": []}

        try:
            normalized_path = str(path).replace("\\", "/").strip()
            if not normalized_path.startswith("/"):
                normalized_path = f"/{normalized_path}"
            normalized_path = normalized_path.rstrip("/") or "/"

            root_item = self._guangya_api.get_item(Path(normalized_path))
            if not root_item:
                return {"error": f"目录不存在: {normalized_path}", "items": []}

            items = self.list_files(root_item, recursion=bool(recursion))
            
            result_items = []
            for item in (items or []):
                entry = {
                    "name": item.name,
                    "type": item.type,
                    "path": item.path,
                    "size": item.size or 0,
                    "extension": item.extension or "",
                    "modify_time": item.modify_time or 0,
                }
                # 为文件添加 stream URL
                if item.type == "file":
                    entry["stream_url"] = f"/plugin/shuk-guangyadisk/stream?path={item.path}"
                result_items.append(entry)

            return {
                "path": normalized_path,
                "name": root_item.name,
                "type": root_item.type,
                "items": result_items,
                "stream_base": "/plugin/shuk-guangyadisk/stream",
                "browse_base": "/plugin/shuk-guangyadisk/browse",
                "total_files": len([i for i in result_items if i["type"] == "file"]),
                "total_dirs": len([i for i in result_items if i["type"] == "dir"]),
            }
        except Exception as err:
            logger.error(f"【光鸭云盘助手】浏览目录失败: {err}")
            return {"error": str(err), "items": []}

    def webdav(self, request: Request, path: str = "") -> Response:
        """
        WebDAV 协议端点 — 供 Emby / Jellyfin 等媒体服务器直接挂载光鸭云盘为媒体库。
        
        用法:
          - Emby 添加媒体库时选择"网络路径"，填入:
            http://moviepilot-v2:3001/plugin/shuk-guangyadisk/webdav/BMH
          - 或在浏览器中测试: 
            http://你的IP:3001/plugin/shuk-guangyadisk/webdav/
        
        支持的 WebDAV 方法:
          - PROPFIND: 列目录/获取属性（Emby 扫描媒体库核心方法）
          - GET/HEAD: 流式播放文件
          - MKCOL:    创建目录
          - DELETE:   删除
          - PUT:      上传
          - MOVE/COPY: 移动/复制
        
        认证方式: Bearer Token（与 MoviePilot 插件认证一致）
        """
        if not self._enabled or not self._client or not self._guangya_api:
            return Response(
                content='{"error": "插件未启用或未登录"}',
                status_code=503,
                media_type="application/json",
            )

        # 创建 WebDAV Provider 并分发请求
        provider = GuangyaWebDAVProvider(
            guangya_api=self._guangya_api,
            client=self._client,
        )
        return provider.handle_request(request, path or "/")

    def stop_service(self):
        """
        退出插件。
        """
        pass

# =============================================================================
# MoviePilot V3 storage contract
# =============================================================================

"""MoviePilot V3 自定义存储模块合同。

V3 的 StorageChain 会优先通过插件 ``get_module()`` 调用自定义模块。若插件没有
接住自定义存储，请求会继续落到宿主 FileManager，而宿主只认识内置 StorageBase，
最终得到“Unsupported storage type”。本 mixin 同时兼容 V3 新存储名与 V2 历史名，
避免升级后已有整理任务继续引用 ``Shuk-光鸭云盘`` 时失效。

这里也是宿主存储契约的唯一兼容边界：MoviePilot 新增参数时优先在本层适配，
不继续修改 legacy 主体，避免存储协议与业务实现相互污染。
"""

from copy import copy as shallow_copy
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Optional


def _register_storage_selection(func: Callable) -> Callable:
    """在真实 MoviePilot 宿主中注册存储选择事件，独立单测时保持可导入。"""
    try:
        from app.sdk.events import eventmanager
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

    @staticmethod
    def _normalize_posix_path(path: Any) -> str:
        """统一把任意 Windows 或相对路径标准化为 MoviePilot V3 约定的 POSIX 路径。"""
        value = str(path or "/").replace("\\", "/")
        if value in ("", "."):
            return "/"
        if not value.startswith("/"):
            value = f"/{value}"
        value = value.rstrip("/") or "/"
        return value

    def get_folder(self, storage: str, path: Path):
        """适配 V3 ``StorageChain.get_folder(storage, path)``，兼容历史名称。"""
        if not self._matches_storage(storage):
            return None
        if not self._guangya_api:
            return None

        folder = self._guangya_api.get_folder(path)
        if folder is None:
            return None

        if isinstance(folder, dict):
            if "path" in folder:
                folder["path"] = self._normalize_posix_path(folder.get("path"))
            return folder

        existing_path = getattr(folder, "path", None)
        if existing_path is not None:
            folder.path = self._normalize_posix_path(existing_path)
        return folder

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


# =============================================================================
# Organizer V4 (MoviePilot V3 native)
# =============================================================================

import datetime as _organizer_datetime
import re
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.application.directory import DirectoryHelper
from app.application.history import (
    HistoryGateAction,
    describe_history_gate,
    evaluate_history_gate,
    get_transfer_history_repository,
    is_skip_action,
    resolve_history,
)
from app.chain.transfer import TransferChain
from app.runtime.settings import get_runtime_setting
from app.schemas.transfer import EpisodeFormat
from app.schemas.types import MediaType


class GuangYaOrganizerV4:
    """光鸭 V4 自动整理。

    只负责远端发现、稳定性、持久任务状态和串行执行；识别、分类、命名、目标目录、
    覆盖、刮削和整理历史均委托 MoviePilot V3。
    """

    _organizer_config_key = "organize_monitor_config"
    _organizer_tasks_key = "organize_v4_resources"
    _organizer_scan_key = "organize_v4_scan"
    _organizer_history_key = "organize_monitor_history"
    _organizer_status_key = "organize_monitor_status"

    _organizer_heartbeat = 15
    _organizer_lease_seconds = 1800
    _organizer_verify_timeout = 300
    _organizer_history_limit = 100

    _organizer_enabled: bool = False
    _organizer_path: str = "/"
    _organizer_interval: int = 60
    _organizer_stability: int = 30
    _organizer_batch_size: int = 100
    _organizer_recursive: bool = True
    _organizer_last_scan_at: float = 0.0

    _organizer_executor: Optional[ThreadPoolExecutor] = None
    _organizer_future: Optional[Future] = None
    _organizer_lock: Optional[threading.RLock] = None
    _organizer_owner_id: str = ""
    _organizer_stopping: bool = False
    _organizer_graceful_paused: bool = False

    @staticmethod
    def _organizer_normalize_path(value: Any) -> str:
        """规范远端 POSIX 路径。"""
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return "/"
        if not raw.startswith("/"):
            raw = "/" + raw
        path = PurePosixPath(raw)
        if ".." in path.parts:
            raise ValueError("监控目录不能包含 ..")
        normalized = "/" + "/".join(part for part in path.parts if part != "/")
        return normalized.rstrip("/") or "/"

    @staticmethod
    def _organizer_bounded_int(
        value: Any,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        """把配置值限制在安全整数范围。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    def _organizer_default_config(self) -> Dict[str, Any]:
        """返回自动整理默认配置。"""
        return {
            "enabled": False,
            "path": "/",
            "interval": 60,
            "stability": 30,
            "batch_size": 100,
            "recursive": True,
        }

    def _organizer_load_config(self) -> Dict[str, Any]:
        """从 MoviePilot 插件数据区加载自动整理配置。"""
        config = self._organizer_default_config()
        saved = self.get_data(self._organizer_config_key) or {}
        if isinstance(saved, dict):
            config.update(saved)
        config["enabled"] = bool(config.get("enabled"))
        config["path"] = self._organizer_normalize_path(config.get("path") or "/")
        config["interval"] = self._organizer_bounded_int(
            config.get("interval"), 60, 15, 3600
        )
        config["stability"] = self._organizer_bounded_int(
            config.get("stability"), 30, 0, 3600
        )
        config["batch_size"] = self._organizer_bounded_int(
            config.get("batch_size"), 100, 1, 500
        )
        config["recursive"] = bool(config.get("recursive", True))
        return config

    def _organizer_init(self) -> None:
        """恢复 V4 自动整理运行态，不访问远端。"""
        config = self._organizer_load_config()
        self._organizer_enabled = config["enabled"]
        self._organizer_path = config["path"]
        self._organizer_interval = config["interval"]
        self._organizer_stability = config["stability"]
        self._organizer_batch_size = config["batch_size"]
        self._organizer_recursive = config["recursive"]
        self._organizer_lock = self._organizer_lock or threading.RLock()
        if not self._organizer_owner_id:
            self._organizer_owner_id = uuid.uuid4().hex
        self._organizer_stopping = False
        persisted_scan = self.get_data(self._organizer_scan_key) or {}
        if isinstance(persisted_scan, dict):
            self._organizer_last_scan_at = float(
                persisted_scan.get("completed_at")
                or persisted_scan.get("updated_at")
                or 0
            )
        if self._organizer_enabled:
            self._organizer_graceful_paused = False
        if self._organizer_executor is None:
            self._organizer_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="guangya-organizer-v4",
            )
        self._organizer_recover_expired_leases()
        logger.info(
            "【光鸭云盘助手】【V4整理】恢复设置: enabled=%s path=%s interval=%ss stability=%ss batch=%s recursive=%s",
            self._organizer_enabled,
            self._organizer_path,
            self._organizer_interval,
            self._organizer_stability,
            self._organizer_batch_size,
            self._organizer_recursive,
        )

    def _organizer_stop(self) -> None:
        """停止接收新任务；已运行任务保留租约并允许自然收尾。"""
        self._organizer_stopping = True
        executor = self._organizer_executor
        self._organizer_executor = None
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception as err:
                logger.debug("【光鸭云盘助手】【V4整理】关闭执行器失败: %s", err)

    def get_service(self) -> List[Dict[str, Any]]:
        """向 MoviePilot 声明启动自检和轻量心跳服务。"""
        return [
            {
                "id": "ShukGuangYaDiskV4Bootstrap",
                "name": "光鸭云盘 V4 自动整理启动自检",
                "trigger": DateTrigger(
                    run_date=_organizer_datetime.datetime.now()
                    + _organizer_datetime.timedelta(seconds=5)
                ),
                "func": self.organizer_tick,
                "kwargs": {},
            },
            {
                "id": "ShukGuangYaDiskV4Monitor",
                "name": "光鸭云盘 V4 自动整理监控",
                "trigger": IntervalTrigger(seconds=self._organizer_heartbeat),
                "func": self.organizer_tick,
                "kwargs": {},
            },
        ]

    def _organizer_tasks(self) -> Dict[str, Dict[str, Any]]:
        """读取持久资源任务表。"""
        raw = self.get_data(self._organizer_tasks_key) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _organizer_save_tasks(self, tasks: Dict[str, Dict[str, Any]]) -> None:
        """保存持久资源任务表并限制终态历史体积。"""
        if len(tasks) > 5000:
            terminals = sorted(
                (
                    (path, row)
                    for path, row in tasks.items()
                    if str((row or {}).get("state") or "")
                    in {"COMPLETED", "BLOCKED"}
                ),
                key=lambda pair: float((pair[1] or {}).get("updated_at") or 0),
            )
            for path, _ in terminals[: max(0, len(tasks) - 4500)]:
                tasks.pop(path, None)
        self.save_data(self._organizer_tasks_key, tasks)

    @staticmethod
    def _organizer_fingerprint(item: Any) -> str:
        """生成远端文件版本指纹。"""
        return "|".join(
            [
                str(getattr(item, "fileid", "") or ""),
                str(int(getattr(item, "size", 0) or 0)),
                str(int(float(getattr(item, "modify_time", 0) or 0))),
            ]
        )

    def _organizer_media_extensions(self) -> set[str]:
        """读取 MoviePilot 当前媒体扩展名配置。"""
        raw = get_runtime_setting("RMT_MEDIAEXT", [])
        if isinstance(raw, str):
            values = re.split(r"[,;|\s]+", raw)
        else:
            values = list(raw or [])
        extensions = {
            str(value).strip().lower()
            for value in values
            if str(value).strip()
        }
        normalized = {
            value if value.startswith(".") else f".{value}"
            for value in extensions
        }
        if normalized:
            return normalized
        return {
            ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts",
            ".m2ts", ".flv", ".webm", ".rmvb", ".iso",
        }

    def _organizer_is_candidate(self, item: Any) -> bool:
        """判断远端文件是否属于 MoviePilot 可整理主媒体候选。"""
        if str(getattr(item, "type", "") or "") != "file":
            return False
        name = str(getattr(item, "name", "") or "")
        if not name or name.startswith("."):
            return False
        return Path(name).suffix.lower() in self._organizer_media_extensions()

    def _organizer_observe(self, item: Any, group_path: str) -> None:
        """把一次远端文件观测合并进持久资源状态机。"""
        path = self._organizer_normalize_path(getattr(item, "path", ""))
        if path == "/":
            return
        now = time.time()
        fingerprint = self._organizer_fingerprint(item)
        tasks = self._organizer_tasks()
        current = dict(tasks.get(path) or {})
        previous_fp = str(current.get("fingerprint") or "")

        if current and previous_fp == fingerprint:
            state = str(current.get("state") or "")
            if state == "STABILIZING":
                stable_since = float(current.get("stable_since") or now)
                if now - stable_since >= self._organizer_stability:
                    current["state"] = "READY"
                    current["updated_at"] = now
            current.update(
                {
                    "name": str(getattr(item, "name", "") or Path(path).name),
                    "size": int(getattr(item, "size", 0) or 0),
                    "modify_time": float(getattr(item, "modify_time", 0) or 0),
                    "fileid": str(getattr(item, "fileid", "") or ""),
                    "group_path": self._organizer_normalize_path(group_path),
                    "last_seen": now,
                }
            )
            tasks[path] = current
            self._organizer_save_tasks(tasks)
            return

        modify_time = float(getattr(item, "modify_time", 0) or 0)
        if current:
            stable_since = now
        elif 0 < modify_time <= now:
            stable_since = min(now, modify_time)
        else:
            stable_since = now

        state = (
            "READY"
            if now - stable_since >= self._organizer_stability
            else "STABILIZING"
        )
        tasks[path] = {
            "path": path,
            "name": str(getattr(item, "name", "") or Path(path).name),
            "storage": self._disk_name,
            "size": int(getattr(item, "size", 0) or 0),
            "modify_time": modify_time,
            "fileid": str(getattr(item, "fileid", "") or ""),
            "group_path": self._organizer_normalize_path(group_path),
            "fingerprint": fingerprint,
            "state": state,
            "first_seen": float(current.get("first_seen") or now),
            "stable_since": stable_since,
            "last_seen": now,
            "updated_at": now,
            "attempts": 0 if previous_fp != fingerprint else int(current.get("attempts") or 0),
            "next_run": 0.0,
            "lease_owner": "",
            "lease_until": 0.0,
            "last_error": "",
            "verify_started_at": 0.0,
        }
        self._organizer_save_tasks(tasks)

    def _organizer_scan_state(self, force_restart: bool = False) -> Dict[str, Any]:
        """读取或建立持续 BFS 扫描游标。"""
        root = self._organizer_path
        state = self.get_data(self._organizer_scan_key) or {}
        if (
            force_restart
            or not isinstance(state, dict)
            or self._organizer_normalize_path(state.get("root") or "/") != root
            or not state.get("active")
        ):
            state = {
                "active": True,
                "root": root,
                "queue": [root],
                "seen": [root],
                "cycle_started_at": time.time(),
                "dirs_scanned": 0,
                "files_seen": 0,
                "candidates": 0,
                "errors": 0,
            }
        return dict(state)

    def _organizer_scan_step(
        self,
        *,
        force_restart: bool = False,
        budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """按持久 BFS 游标扫描有限数量目录并发现资源。"""
        if not self._guangya_api:
            return {"success": False, "message": "光鸭云盘尚未登录或存储未初始化"}
        if self._organizer_path == "/":
            return {"success": False, "message": "请先选择具体监控目录，禁止扫描根目录"}

        state = self._organizer_scan_state(force_restart=force_restart)
        queue = list(state.get("queue") or [])
        seen = set(state.get("seen") or [])
        limit = max(1, int(budget or self._organizer_batch_size))
        processed = 0

        while queue and processed < limit:
            directory_path = self._organizer_normalize_path(queue.pop(0))
            processed += 1
            try:
                directory = self._guangya_api.refresh_item(Path(directory_path))
                if not directory:
                    continue
                if str(getattr(directory, "type", "") or "") != "dir":
                    continue
                children = list(self._guangya_api.list_strict(directory) or [])
                state["dirs_scanned"] = int(state.get("dirs_scanned") or 0) + 1
                for child in children:
                    name = str(getattr(child, "name", "") or "")
                    if not name or name.startswith("."):
                        continue
                    if str(getattr(child, "type", "") or "") == "dir":
                        if self._organizer_recursive:
                            child_path = self._organizer_normalize_path(
                                getattr(child, "path", "")
                            )
                            if child_path not in seen:
                                seen.add(child_path)
                                queue.append(child_path)
                        continue
                    state["files_seen"] = int(state.get("files_seen") or 0) + 1
                    if self._organizer_is_candidate(child):
                        self._organizer_observe(child, directory_path)
                        state["candidates"] = int(state.get("candidates") or 0) + 1
            except Exception as err:
                state["errors"] = int(state.get("errors") or 0) + 1
                queue.append(directory_path)
                logger.warning(
                    "【光鸭云盘助手】【V4整理】【扫描】目录读取失败，保留游标下轮继续: %s - %s",
                    directory_path,
                    err,
                )
                break

        state["queue"] = queue
        state["seen"] = list(seen)
        state["updated_at"] = time.time()
        if not queue:
            state["active"] = False
            state["completed_at"] = time.time()
            self._organizer_last_scan_at = time.time()
        self.save_data(self._organizer_scan_key, state)
        self._organizer_status_update(
            scan_active=bool(state.get("active")),
            scan_remaining=len(queue),
            scan_dirs=int(state.get("dirs_scanned") or 0),
            scan_files=int(state.get("files_seen") or 0),
            scan_candidates=int(state.get("candidates") or 0),
            scan_errors=int(state.get("errors") or 0),
            last_scan_at=float(state.get("completed_at") or 0),
        )
        return {
            "success": True,
            "message": "V4 目录扫描已推进",
            "data": {
                "processed_dirs": processed,
                "remaining_dirs": len(queue),
                "cycle_complete": not queue,
                "dirs_scanned": int(state.get("dirs_scanned") or 0),
                "files_seen": int(state.get("files_seen") or 0),
                "candidates": int(state.get("candidates") or 0),
                "errors": int(state.get("errors") or 0),
            },
        }

    def _organizer_recover_expired_leases(self) -> int:
        """把热重载或崩溃遗留的过期 RUNNING 任务恢复为 READY。"""
        tasks = self._organizer_tasks()
        now = time.time()
        recovered = 0
        for row in tasks.values():
            if (
                str(row.get("state") or "") == "RUNNING"
                and float(row.get("lease_until") or 0) <= now
            ):
                row["state"] = "READY"
                row["lease_owner"] = ""
                row["lease_until"] = 0.0
                row["updated_at"] = now
                row["last_error"] = "上一个执行租约已过期，已恢复"
                recovered += 1
        if recovered:
            self._organizer_save_tasks(tasks)
            logger.warning(
                "【光鸭云盘助手】【V4整理】恢复过期执行租约=%s",
                recovered,
            )
        return recovered

    def _organizer_next_task(self) -> Optional[Dict[str, Any]]:
        """选择第一个可执行任务，明确跳过 STABILIZING/等待项。"""
        tasks = self._organizer_tasks()
        now = time.time()
        candidates = []
        for path, row in tasks.items():
            state = str((row or {}).get("state") or "")
            if state not in {"READY", "RETRY", "VERIFYING"}:
                continue
            if float((row or {}).get("next_run") or 0) > now:
                continue
            candidates.append((float((row or {}).get("first_seen") or 0), path, dict(row)))
        if not candidates:
            return None
        _, _, selected = min(candidates, key=lambda item: (item[0], item[1]))
        return selected

    def _organizer_claim(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """以实例租约原子认领一个持久任务。"""
        path = str(task.get("path") or "")
        if not path:
            return None
        tasks = self._organizer_tasks()
        current = dict(tasks.get(path) or {})
        now = time.time()
        if str(current.get("state") or "") not in {"READY", "RETRY", "VERIFYING"}:
            return None
        if float(current.get("next_run") or 0) > now:
            return None
        current["state"] = "RUNNING"
        current["run_mode"] = (
            "verify" if str(task.get("state") or "") == "VERIFYING" else "execute"
        )
        current["lease_owner"] = self._organizer_owner_id
        current["lease_until"] = now + self._organizer_lease_seconds
        current["attempts"] = int(current.get("attempts") or 0) + 1
        current["updated_at"] = now
        tasks[path] = current
        self._organizer_save_tasks(tasks)
        return dict(current)

    def _organizer_dispatch_next(self) -> Dict[str, Any]:
        """若执行器空闲，立即选择并提交下一个 READY/RETRY/VERIFYING 任务。"""
        if self._organizer_stopping:
            return {"scheduled": False, "reason": "stopping"}
        if self._organizer_graceful_paused:
            return {"scheduled": False, "reason": "graceful_paused"}
        lock = self._organizer_lock or threading.RLock()
        self._organizer_lock = lock
        with lock:
            if self._organizer_stopping:
                return {"scheduled": False, "reason": "stopping"}
            if self._organizer_graceful_paused:
                return {"scheduled": False, "reason": "graceful_paused"}
            if self._organizer_future is not None and not self._organizer_future.done():
                return {"scheduled": False, "reason": "worker_busy"}
            task = self._organizer_next_task()
            if not task:
                return {"scheduled": False, "reason": "no_ready"}
            claimed = self._organizer_claim(task)
            if not claimed:
                return {"scheduled": False, "reason": "state_changed"}
            if self._organizer_executor is None:
                self._organizer_executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="guangya-organizer-v4",
                )
            future = self._organizer_executor.submit(
                self._organizer_run_claimed,
                claimed,
            )
            self._organizer_future = future
            future.add_done_callback(self._organizer_done_callback)
            self._organizer_status_update(
                runtime_phase="running",
                current_task_path=str(claimed.get("path") or ""),
            )
            logger.info(
                "【光鸭云盘助手】【V4整理】提交任务: %s mode=%s",
                claimed.get("path"),
                claimed.get("run_mode"),
            )
            return {
                "scheduled": True,
                "path": claimed.get("path"),
                "mode": claimed.get("run_mode"),
            }

    def _organizer_directory_context(
        self,
        path: str,
    ) -> Tuple[Optional[Any], Optional[MediaType]]:
        """读取 MoviePilot 当前目录映射，并返回目标目录配置与媒体类型提示。"""
        source = Path(path)
        helper = DirectoryHelper()
        target_directory = helper.get_dir(
            media=None,
            include_unsorted=False,
            storage=self._disk_name,
            src_path=source,
        )
        mtype = None
        if target_directory and getattr(target_directory, "media_type", None):
            try:
                mtype = MediaType(target_directory.media_type)
            except (TypeError, ValueError):
                mtype = None
        if mtype is None:
            for part in reversed(source.parts[:-1]):
                match = re.fullmatch(r"(?:S|Season\s*)0*(\d{1,2})", part, re.IGNORECASE)
                if match or re.fullmatch(r"第\s*0*\d{1,2}\s*季", part):
                    mtype = MediaType.TV
                    break
        return target_directory, mtype

    @staticmethod
    def _organizer_season_from_path(path: str) -> Optional[int]:
        """从标准 Season 目录名中提取季号，仅作为高置信度提示。"""
        for part in reversed(Path(path).parts[:-1]):
            match = re.fullmatch(
                r"(?:S|Season\s*)0*(\d{1,2})",
                part,
                re.IGNORECASE,
            )
            if match:
                return int(match.group(1))
            match = re.fullmatch(r"第\s*0*(\d{1,2})\s*季", part)
            if match:
                return int(match.group(1))
        return None

    def _organizer_episode_format(
        self,
        chain: TransferChain,
        current: Any,
        mtype: Optional[MediaType],
    ) -> Optional[EpisodeFormat]:
        """让 MoviePilot 自己根据同目录样本推荐剧集定位格式。"""
        if mtype != MediaType.TV:
            return None
        try:
            parent_path = self._organizer_normalize_path(
                str(Path(current.path).parent)
            )
            parent = self._guangya_api.get_item(Path(parent_path))
            if not parent:
                return None
            siblings = [
                item
                for item in (self._guangya_api.list_strict(parent) or [])
                if self._organizer_is_candidate(item)
            ]
            if not siblings:
                return None
            state, _, data = chain.recommend_episode_format(
                fileitem=None,
                fileitems=siblings,
            )
            if not state or not isinstance(data, dict):
                return None
            episode_format = str(data.get("episode_format") or "").strip()
            if not episode_format:
                return None
            return EpisodeFormat(
                format=episode_format,
                detail=data.get("episode_detail"),
                part=data.get("episode_part"),
                offset=data.get("episode_offset"),
            )
        except Exception as err:
            logger.debug(
                "【光鸭云盘助手】【V4整理】MoviePilot 集数格式推荐未命中: %s",
                err,
            )
            return None

    def _organizer_history_gate(self, current: Any) -> Dict[str, Any]:
        """使用 MoviePilot 原生历史闸判断当前文件是否需要继续整理。"""
        try:
            history = resolve_history(
                str(current.path),
                storage=self._disk_name,
                transfer_history_oper=get_transfer_history_repository(),
            )
        except Exception as err:
            return {
                "ok": False,
                "retry": True,
                "message": f"MoviePilot 整理历史查询失败: {err}",
            }
        action = evaluate_history_gate(
            history,
            file_size=getattr(current, "size", None),
            file_modify_time=getattr(current, "modify_time", None),
            fileid=getattr(current, "fileid", None),
            retry_count=getattr(history, "retry_count", None),
        )
        description = describe_history_gate(
            history,
            file_size=getattr(current, "size", None),
            file_modify_time=getattr(current, "modify_time", None),
            fileid=getattr(current, "fileid", None),
        )
        if action == HistoryGateAction.SKIP_RETRY_EXHAUSTED:
            return {
                "ok": False,
                "blocked": True,
                "message": description,
            }
        if is_skip_action(action):
            return {
                "ok": False,
                "completed": True,
                "message": description,
            }
        return {"ok": True, "message": description}

    @staticmethod
    def _organizer_preview_audit(
        source_path: str,
        payload: Any,
    ) -> Tuple[bool, str]:
        """校验 MoviePilot 预览至少包含当前源并保持目标一一映射。"""
        if not isinstance(payload, dict):
            return False, "MoviePilot 预览未返回结构化结果"
        rows = [row for row in (payload.get("items") or []) if isinstance(row, dict)]
        if not rows:
            return False, "MoviePilot 预览没有返回文件项"
        normalized_source = str(source_path).replace("\\", "/").rstrip("/")
        current_found = False
        targets: Dict[str, str] = {}
        for row in rows:
            source = str(row.get("source") or "").replace("\\", "/").rstrip("/")
            target = str(row.get("target") or "").replace("\\", "/").rstrip("/")
            if source == normalized_source:
                current_found = True
                if not bool(row.get("success")):
                    return False, str(row.get("message") or "当前源文件预览失败")
                if not target:
                    return False, "当前源文件预览没有目标路径"
            if bool(row.get("success")) and target:
                previous = targets.get(target)
                if previous and previous != source:
                    return False, f"多个源文件映射到同一目标: {previous} / {source} -> {target}"
                targets[target] = source
        if not current_found:
            return False, "MoviePilot 预览缺少当前源文件"
        return True, ""

    def _organizer_verify_history(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """只验证 MoviePilot 历史，不重复执行已经提交成功的整理。"""
        path = str(task.get("path") or "")
        try:
            history = resolve_history(
                path,
                storage=self._disk_name,
                transfer_history_oper=get_transfer_history_repository(),
            )
        except Exception as err:
            return {
                "state": "VERIFYING",
                "message": f"整理已执行，等待历史确认失败: {err}",
                "next_run": time.time() + 10,
            }
        if history is not None and bool(getattr(history, "status", False)):
            return {
                "state": "COMPLETED",
                "message": "MoviePilot 成功历史已确认",
            }
        started = float(task.get("verify_started_at") or time.time())
        if time.time() - started >= self._organizer_verify_timeout:
            return {
                "state": "BLOCKED",
                "message": "整理执行返回成功，但 5 分钟内未获得 MoviePilot 成功历史；已停止重复执行并等待人工核验",
            }
        return {
            "state": "VERIFYING",
            "message": "整理执行已返回成功，等待 MoviePilot 成功历史",
            "next_run": time.time() + 10,
        }

    def _organizer_execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """执行一次 MoviePilot 预览、真实整理和历史终态确认。"""
        path = str(task.get("path") or "")
        try:
            current = self._guangya_api.refresh_item(Path(path))
        except Exception as err:
            return {
                "state": "RETRY",
                "message": f"读取源文件失败: {err}",
                "next_run": time.time() + min(300, 5 * max(1, int(task.get("attempts") or 1))),
            }
        if not current:
            # 源路径消失不能自动等价于成功：远端 move 可能已经发生但最终命名/确认失败。
            try:
                history = resolve_history(
                    path,
                    storage=self._disk_name,
                    transfer_history_oper=get_transfer_history_repository(),
                )
            except Exception as err:
                return {
                    "state": "BLOCKED",
                    "message": f"源文件已消失且 MoviePilot 历史无法确认，拒绝推断成功: {err}",
                }
            if history is not None and bool(getattr(history, "status", False)):
                return {
                    "state": "COMPLETED",
                    "message": "源文件已消失，MoviePilot 成功历史已确认",
                }
            return {
                "state": "BLOCKED",
                "message": "源文件已消失但没有 MoviePilot 成功历史；可能是远端移动/重命名终态不确定，已停止自动重试",
            }

        gate = self._organizer_history_gate(current)
        if gate.get("completed"):
            return {"state": "COMPLETED", "message": gate.get("message") or "已整理"}
        if gate.get("blocked"):
            return {"state": "BLOCKED", "message": gate.get("message") or "MoviePilot 已停止重试"}
        if not gate.get("ok"):
            return {
                "state": "RETRY",
                "message": gate.get("message") or "历史门控暂不可用",
                "next_run": time.time() + 15,
            }

        target_directory, mtype = self._organizer_directory_context(path)
        chain = TransferChain()
        epformat = self._organizer_episode_format(chain, current, mtype)
        season = self._organizer_season_from_path(path)

        kwargs = {
            "fileitem": current,
            "mtype": mtype,
            "target_directory": target_directory,
            "season": season,
            "epformat": epformat,
            "background": False,
            "sync_extra_files": True,
        }

        try:
            preview_ok, preview_payload = chain.do_transfer(
                **kwargs,
                preview=True,
            )
        except Exception as err:
            return {
                "state": "RETRY",
                "message": f"MoviePilot 预览异常: {err}",
                "next_run": time.time() + 15,
            }
        if not preview_ok:
            return {
                "state": "RETRY",
                "message": f"MoviePilot 预览失败: {preview_payload}",
                "next_run": time.time() + 30,
            }
        audit_ok, audit_message = self._organizer_preview_audit(path, preview_payload)
        if not audit_ok:
            return {
                "state": "BLOCKED",
                "message": f"安全预览阻止真实整理: {audit_message}",
            }

        try:
            state, result = chain.do_transfer(
                **kwargs,
                preview=False,
            )
        except Exception as err:
            return {
                "state": "RETRY",
                "message": f"MoviePilot 整理异常: {err}",
                "next_run": time.time() + 30,
            }
        if not state:
            return {
                "state": "RETRY",
                "message": f"MoviePilot 整理失败: {result}",
                "next_run": time.time() + min(
                    600,
                    30 * max(1, int(task.get("attempts") or 1)),
                ),
            }

        verify_task = dict(task)
        verify_task["verify_started_at"] = time.time()
        verified = self._organizer_verify_history(verify_task)
        if verified.get("state") == "VERIFYING":
            verified["verify_started_at"] = verify_task["verify_started_at"]
        return verified

    def _organizer_run_claimed(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """执行已认领任务；VERIFYING 只做终态核验，不重复移动。"""
        if str(task.get("run_mode") or "") == "verify":
            return self._organizer_verify_history(task)
        return self._organizer_execute_task(task)

    def _organizer_done_callback(self, future: Future) -> None:
        """收口执行结果并立即调度下一 READY 任务，不等待下一次 heartbeat。"""
        try:
            result = future.result()
            if not isinstance(result, dict):
                result = {"state": "RETRY", "message": f"非法执行结果: {result!r}"}
        except Exception as err:
            result = {"state": "RETRY", "message": f"执行器异常: {err}"}

        lock = self._organizer_lock or threading.RLock()
        self._organizer_lock = lock
        with lock:
            tasks = self._organizer_tasks()
            owned_path = ""
            for path, row in tasks.items():
                if (
                    str((row or {}).get("state") or "") == "RUNNING"
                    and str((row or {}).get("lease_owner") or "") == self._organizer_owner_id
                ):
                    owned_path = path
                    current = dict(row)
                    state = str(result.get("state") or "RETRY")
                    current["state"] = state
                    current["lease_owner"] = ""
                    current["lease_until"] = 0.0
                    current["updated_at"] = time.time()
                    current["last_error"] = str(result.get("message") or "")
                    current["next_run"] = float(result.get("next_run") or 0)
                    if state == "VERIFYING":
                        current["verify_started_at"] = float(
                            result.get("verify_started_at")
                            or current.get("verify_started_at")
                            or time.time()
                        )
                    elif state == "COMPLETED":
                        current["completed_at"] = time.time()
                        current["verify_started_at"] = 0.0
                    elif state == "BLOCKED":
                        current["blocked_at"] = time.time()
                    tasks[path] = current
                    self._organizer_history_append(
                        path=path,
                        state=state,
                        message=current["last_error"],
                    )
                    break
            self._organizer_save_tasks(tasks)
            self._organizer_future = None
            self._organizer_status_update(
                runtime_phase="idle",
                current_task_path="",
                last_result_path=owned_path,
                last_result_state=str(result.get("state") or ""),
                last_result_message=str(result.get("message") or ""),
            )

        # 完成后立刻消费下一个 READY；STABILIZING/RETRY_WAIT 不会阻塞后续 ready。
        self._organizer_dispatch_next()

    def _organizer_history_append(self, *, path: str, state: str, message: str) -> None:
        """追加最近整理记录。"""
        rows = list(self.get_data(self._organizer_history_key) or [])
        rows.append(
            {
                "time": int(time.time()),
                "path": path,
                "state": state,
                "message": message,
            }
        )
        self.save_data(
            self._organizer_history_key,
            rows[-self._organizer_history_limit :],
        )

    def _organizer_status_update(self, **values: Any) -> None:
        """合并保存运行状态。"""
        status = self.get_data(self._organizer_status_key) or {}
        if not isinstance(status, dict):
            status = {}
        status.update(values)
        status["updated_at"] = time.time()
        self.save_data(self._organizer_status_key, status)

    def _organizer_stats(self) -> Dict[str, int]:
        """统计各资源状态数量。"""
        counts: Dict[str, int] = {}
        for row in self._organizer_tasks().values():
            state = str((row or {}).get("state") or "UNKNOWN")
            counts[state] = counts.get(state, 0) + 1
        return counts

    def organizer_tick(self) -> None:
        """自动整理 heartbeat：扫描与执行彼此独立，Worker 忙时仍继续发现。"""
        if not self._organizer_enabled:
            return
        if not self._enabled or not self._guangya_api:
            self._organizer_status_update(
                running=False,
                last_error="光鸭云盘未启用或未登录",
            )
            return
        now = time.time()
        try:
            self._organizer_recover_expired_leases()
            scan_state = self.get_data(self._organizer_scan_key) or {}
            scan_active = bool(isinstance(scan_state, dict) and scan_state.get("active"))
            if scan_active or now - self._organizer_last_scan_at >= self._organizer_interval:
                self._organizer_scan_step(
                    force_restart=not scan_active,
                    budget=self._organizer_batch_size,
                )
            dispatch = self._organizer_dispatch_next()
            self._organizer_status_update(
                running=True,
                last_tick=now,
                dispatch=dispatch,
                task_stats=self._organizer_stats(),
                last_error="",
            )
        except Exception as err:
            logger.error("【光鸭云盘助手】【V4整理】heartbeat 异常: %s", err)
            self._organizer_status_update(
                running=True,
                last_tick=now,
                last_error=str(err),
            )

    def api_organize_policies(self) -> Dict[str, Any]:
        """说明分类、命名和目标策略由 MoviePilot 管理。"""
        return {
            "success": True,
            "message": "分类、命名、目标目录、覆盖和刮削全部由 MoviePilot V3 管理",
            "data": {"managed_by": "MoviePilot"},
        }

    def api_organize_folders(self, payload: dict) -> Dict[str, Any]:
        """浏览可选监控目录。"""
        if not self._guangya_api:
            return {"success": False, "message": "光鸭云盘尚未登录或存储未初始化"}
        try:
            path = self._organizer_normalize_path((payload or {}).get("path") or "/")
            folder = self._guangya_api.get_item(Path(path))
            if not folder or str(getattr(folder, "type", "") or "") != "dir":
                return {"success": False, "message": f"目录不存在: {path}"}
            rows = []
            for item in self._guangya_api.list_strict(folder) or []:
                if (
                    str(getattr(item, "type", "") or "") == "dir"
                    and not str(getattr(item, "name", "") or "").startswith(".")
                ):
                    rows.append(
                        {
                            "name": item.name,
                            "path": self._organizer_normalize_path(item.path),
                            "fileid": str(item.fileid or ""),
                            "modify_time": int(item.modify_time or 0),
                        }
                    )
            parent = (
                "/"
                if path == "/"
                else self._organizer_normalize_path(str(PurePosixPath(path).parent))
            )
            return {
                "success": True,
                "data": {"path": path, "parent": parent, "folders": rows},
            }
        except Exception as err:
            return {"success": False, "message": f"浏览目录失败: {err}"}

    def api_organize_monitor_config(self) -> Dict[str, Any]:
        """读取 V4 自动整理配置。"""
        return {
            "success": True,
            "data": {
                "config": self._organizer_load_config(),
                "managed_by": "MoviePilot V3",
            },
        }

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        """保存 V4 自动整理配置并立即更新运行态。"""
        try:
            current = self._organizer_load_config()
            incoming = payload or {}
            config = {
                "enabled": bool(incoming.get("enabled", current["enabled"])),
                "path": self._organizer_normalize_path(
                    incoming.get("path", current["path"])
                ),
                "interval": self._organizer_bounded_int(
                    incoming.get("interval", current["interval"]), 60, 15, 3600
                ),
                "stability": self._organizer_bounded_int(
                    incoming.get("stability", current["stability"]), 30, 0, 3600
                ),
                "batch_size": self._organizer_bounded_int(
                    incoming.get("batch_size", current["batch_size"]), 100, 1, 500
                ),
                "recursive": bool(
                    incoming.get("recursive", current["recursive"])
                ),
            }
            if config["enabled"] and config["path"] == "/":
                return {"success": False, "message": "自动整理禁止监控根目录 /"}
            old_path = self._organizer_path
            self.save_data(self._organizer_config_key, config)
            self._organizer_enabled = config["enabled"]
            if self._organizer_enabled:
                self._organizer_graceful_paused = False
            self._organizer_path = config["path"]
            self._organizer_interval = config["interval"]
            self._organizer_stability = config["stability"]
            self._organizer_batch_size = config["batch_size"]
            self._organizer_recursive = config["recursive"]
            self._organizer_last_scan_at = 0.0
            if old_path != self._organizer_path:
                self.save_data(self._organizer_scan_key, {})
            return {
                "success": True,
                "message": "V4 自动整理设置已保存",
                "data": {"config": config},
            }
        except Exception as err:
            return {"success": False, "message": f"保存自动整理设置失败: {err}"}

    def api_organize_monitor_scan(self, payload: dict = None) -> Dict[str, Any]:
        """从监控根重新开始一轮强制扫描，并立即尝试执行 READY 任务。"""
        result = self._organizer_scan_step(
            force_restart=True,
            budget=max(self._organizer_batch_size, 100),
        )
        if isinstance(result, dict):
            result.setdefault("data", {})["dispatch"] = self._organizer_dispatch_next()
        return result

    def api_organize_monitor_incremental_scan(self, payload: dict = None) -> Dict[str, Any]:
        """继续当前 BFS 扫描游标。"""
        result = self._organizer_scan_step(
            force_restart=False,
            budget=max(self._organizer_batch_size, 100),
        )
        if isinstance(result, dict):
            result.setdefault("data", {})["dispatch"] = self._organizer_dispatch_next()
        return result

    def api_organize_monitor_full_scan(self, payload: dict = None) -> Dict[str, Any]:
        """兼容旧前端：V4 全量扫描等价于从根重建 BFS 游标。"""
        return self.api_organize_monitor_scan(payload)

    def api_organize_monitor_full_scan_stop(self, payload: dict = None) -> Dict[str, Any]:
        """停止当前 BFS 扫描，但保留已经发现的资源任务。"""
        state = self.get_data(self._organizer_scan_key) or {}
        if not isinstance(state, dict):
            state = {}
        state["active"] = False
        state["queue"] = []
        state["stopped_at"] = time.time()
        self.save_data(self._organizer_scan_key, state)
        return {
            "success": True,
            "message": "已停止当前扫描；已发现任务仍保留",
        }

    def api_organize_monitor_unblock(self, payload: dict = None) -> Dict[str, Any]:
        """解除 BLOCKED 任务并重新进入 READY。"""
        tasks = self._organizer_tasks()
        count = 0
        now = time.time()
        for row in tasks.values():
            if str((row or {}).get("state") or "") == "BLOCKED":
                row["state"] = "READY"
                row["next_run"] = 0.0
                row["updated_at"] = now
                row["last_error"] = ""
                count += 1
        self._organizer_save_tasks(tasks)
        self._organizer_dispatch_next()
        return {
            "success": True,
            "message": f"已解除 {count} 个阻塞任务",
            "data": {"unblocked": count},
        }

    def api_organize_monitor_graceful_stop(self, payload: dict = None) -> Dict[str, Any]:
        """暂停自动监控；当前 RUNNING 自然收尾，持久待处理任务全部保留。"""
        self._organizer_graceful_paused = True
        self._organizer_enabled = False

        config = self._organizer_load_config()
        config["enabled"] = False
        self.save_data(self._organizer_config_key, config)

        scan = self.get_data(self._organizer_scan_key) or {}
        if not isinstance(scan, dict):
            scan = {}
        scan["active"] = False
        scan["queue"] = []
        scan["graceful_stopped_at"] = time.time()
        self.save_data(self._organizer_scan_key, scan)

        busy = bool(self._organizer_future and not self._organizer_future.done())
        self._organizer_status_update(
            runtime_phase="finishing_current" if busy else "paused",
            graceful_stop_state="finishing_current" if busy else "paused",
            graceful_stop_message=(
                "当前任务完成后暂停；READY/RETRY/VERIFYING 任务全部保留，不会清空或误删"
                if busy
                else "自动监控已暂停；持久待处理任务全部保留"
            ),
        )
        return {
            "success": True,
            "message": (
                "已停止继续派发；当前任务将自然收尾"
                if busy
                else "自动监控已暂停"
            ),
            "data": {
                "state": "finishing_current" if busy else "paused",
                "pending_preserved": True,
            },
        }

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        """返回 V4 自动整理配置、状态和最近结果。"""
        status = self.get_data(self._organizer_status_key) or {}
        if not isinstance(status, dict):
            status = {}
        scan = self.get_data(self._organizer_scan_key) or {}
        if not isinstance(scan, dict):
            scan = {}
        history = list(self.get_data(self._organizer_history_key) or [])[-20:][::-1]
        tasks = self._organizer_tasks()
        samples = sorted(
            (
                {
                    "path": path,
                    "state": row.get("state"),
                    "next_run": row.get("next_run"),
                    "last_error": row.get("last_error"),
                }
                for path, row in tasks.items()
                if str((row or {}).get("state") or "")
                not in {"COMPLETED"}
            ),
            key=lambda row: str(row.get("path") or ""),
        )[:20]
        return {
            "success": True,
            "data": {
                "config": self._organizer_load_config(),
                "status": {
                    **status,
                    "pipeline": "v4-resource-store",
                    "task_stats": self._organizer_stats(),
                    "worker_busy": bool(
                        self._organizer_future
                        and not self._organizer_future.done()
                    ),
                    "scan_active": bool(scan.get("active")),
                    "scan_remaining": len(scan.get("queue") or []),
                    "graceful_stop_state": (
                        "finishing_current"
                        if self._organizer_graceful_paused
                        and self._organizer_future
                        and not self._organizer_future.done()
                        else "paused"
                        if self._organizer_graceful_paused
                        else ""
                    ),
                    "graceful_stop_message": (
                        "当前任务完成后暂停；持久待处理任务全部保留"
                        if self._organizer_graceful_paused
                        and self._organizer_future
                        and not self._organizer_future.done()
                        else "自动监控已暂停；持久待处理任务全部保留"
                        if self._organizer_graceful_paused
                        else ""
                    ),
                },
                "history": history,
                "pending_sample": samples,
                "mp": {"managed_by": "MoviePilot V3"},
            },
        }

    def api_organize_monitor_diagnostics(self) -> Dict[str, Any]:
        """返回自动整理与上传诊断摘要。"""
        upload_getter = getattr(self._guangya_api, "get_upload_diagnostics", None)
        upload = upload_getter(limit=30) if callable(upload_getter) else {}
        status = self.api_organize_monitor_status()
        return {
            "success": True,
            "message": "V4 诊断数据已生成",
            "data": {
                **dict(status.get("data") or {}),
                "upload": upload,
                "runtime": {
                    "owner_id": self._organizer_owner_id,
                    "executor": self._organizer_executor is not None,
                    "future_running": bool(
                        self._organizer_future
                        and not self._organizer_future.done()
                    ),
                },
            },
        }

    def api_organize_monitor_selfcheck(self) -> Dict[str, Any]:
        """检查当前 V4 Organizer 的 MoviePilot V3 前置条件。"""
        directory = None
        error = ""
        if self._organizer_path != "/":
            try:
                directory = DirectoryHelper().get_dir(
                    media=None,
                    include_unsorted=False,
                    storage=self._disk_name,
                    src_path=Path(self._organizer_path),
                )
            except Exception as err:
                error = str(err)
        healthy = bool(
            self._enabled
            and self._guangya_api
            and self._organizer_path != "/"
            and (directory is not None or not self._organizer_enabled)
        )
        return {
            "success": True,
            "message": "V4 自动整理自检完成",
            "data": {
                "healthy": healthy,
                "plugin_enabled": bool(self._enabled),
                "storage_ready": bool(self._guangya_api),
                "monitor_enabled": bool(self._organizer_enabled),
                "monitor_path": self._organizer_path,
                "moviepilot_directory_match": bool(directory),
                "moviepilot_directory": (
                    getattr(directory, "name", None)
                    or str(getattr(directory, "download_path", "") or "")
                    if directory
                    else None
                ),
                "error": error,
            },
        }

    def get_organizer_api(self) -> List[Dict[str, Any]]:
        """返回与旧 Vue 页面兼容的 V4 Organizer API。"""
        response_model = GuangYaOrganizerResponse
        return [
            {"path": "/organize/policies", "endpoint": self.api_organize_policies, "auth": "bear", "methods": ["GET"], "summary": "查看 MoviePilot V3 整理边界", "response_model": response_model},
            {"path": "/organize/folders", "endpoint": self.api_organize_folders, "auth": "bear", "methods": ["POST"], "summary": "浏览光鸭监控目录", "response_model": response_model},
            {"path": "/organize/monitor/config", "endpoint": self.api_organize_monitor_config, "auth": "bear", "methods": ["GET"], "summary": "读取自动整理监控设置", "response_model": response_model},
            {"path": "/organize/monitor/config", "endpoint": self.api_organize_monitor_save, "auth": "bear", "methods": ["POST"], "summary": "保存自动整理监控设置", "response_model": response_model},
            {"path": "/organize/monitor/scan", "endpoint": self.api_organize_monitor_scan, "auth": "bear", "methods": ["POST"], "summary": "重新扫描并整理", "response_model": response_model},
            {"path": "/organize/monitor/incremental-scan", "endpoint": self.api_organize_monitor_incremental_scan, "auth": "bear", "methods": ["POST"], "summary": "继续增量扫描", "response_model": response_model},
            {"path": "/organize/monitor/full-scan", "endpoint": self.api_organize_monitor_full_scan, "auth": "bear", "methods": ["POST"], "summary": "启动强制全量扫描", "response_model": response_model},
            {"path": "/organize/monitor/full-scan/stop", "endpoint": self.api_organize_monitor_full_scan_stop, "auth": "bear", "methods": ["POST"], "summary": "停止当前扫描", "response_model": response_model},
            {"path": "/organize/monitor/graceful-stop", "endpoint": self.api_organize_monitor_graceful_stop, "auth": "bear", "methods": ["POST"], "summary": "安全暂停自动整理", "response_model": response_model},
            {"path": "/organize/monitor/status", "endpoint": self.api_organize_monitor_status, "auth": "bear", "methods": ["GET"], "summary": "自动整理状态", "response_model": response_model},
            {"path": "/organize/monitor/diagnostics", "endpoint": self.api_organize_monitor_diagnostics, "auth": "bear", "methods": ["GET"], "summary": "自动整理诊断", "response_model": response_model},
            {"path": "/organize/monitor/selfcheck", "endpoint": self.api_organize_monitor_selfcheck, "auth": "bear", "methods": ["GET"], "summary": "自动整理自检", "response_model": response_model},
            {"path": "/organize/monitor/unblock", "endpoint": self.api_organize_monitor_unblock, "auth": "bear", "methods": ["POST"], "summary": "解除阻塞任务", "response_model": response_model},
        ]


# =============================================================================
# Plugin entry (MoviePilot V3)
# =============================================================================

class ShukGuangYaDisk(GuangYaOrganizerV4, V3StorageContractMixin, _LegacyShukGuangYaDisk):
    """光鸭云盘助手 V4：直接基于 MoviePilot V3 正式接口的单文件实现。"""

    plugin_name = "光鸭云盘助手"
    plugin_desc = "MoviePilot V3 光鸭云盘存储助手（V4 重构基线）：登录、浏览、上传下载、WebDAV、Emby 流式代理。"
    plugin_version = "4.0.0-alpha1"
    plugin_author = "liheng-lk"
    plugin_label = "存储,光鸭云盘,MoviePilot,挂载,Emby,WebDAV"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"

    _disk_name = "光鸭云盘助手"
    _legacy_disk_name = "Shuk-光鸭云盘"
    _upload_progress_log: bool = False

    _sms_verification_id: str = ""
    _sms_phone_number: str = ""
    _sms_captcha_token: str = ""

    def _migrate_storage_name(self) -> None:
        """只通过 MoviePilot V3 StorageHelper 注册当前存储，不直写宿主配置。"""
        try:
            storage_helper = StorageHelper()
            storages = storage_helper.get_storagies() or []
            if not any(storage.type == self._disk_name for storage in storages):
                storage_helper.add_storage(
                    storage=self._disk_name,
                    name=self._disk_name,
                    conf={},
                )
                logger.info("【光鸭云盘助手】MoviePilot V3 已注册存储: %s", self._disk_name)
        except Exception as err:
            logger.warning("【光鸭云盘助手】MoviePilot V3 存储注册检查失败: %s", err)

    def init_plugin(self, config: dict = None) -> None:
        config = config or {}
        self._upload_progress_log = bool(
            config.get("upload_progress_log", getattr(self, "_upload_progress_log", False))
        )
        self._migrate_storage_name()
        super().init_plugin(config)
        if self._guangya_api:
            self._guangya_api.upload_progress_log = self._upload_progress_log
        self._organizer_init()

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        return None, {
            "enabled": self._enabled,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "device_id": self._device_id,
            "poll_interval": self._poll_interval or 5,
            "page_size": self._page_size or 100,
            "order_by": self._order_by or 3,
            "sort_type": self._sort_type or 1,
            "permanently_delete": self._permanently_delete,
            "upload_progress_log": self._upload_progress_log,
        }

    def _get_config(self) -> Dict[str, Any]:
        data = super()._get_config()
        data["upload_progress_log"] = self._upload_progress_log
        data["storage_name"] = self._disk_name
        data["remote_status_available"] = True
        data["remote_status_message"] = ""
        if self._access_token and not data.get("logged_in"):
            refresh_invalid = bool(
                self._client
                and getattr(self._client, "last_refresh_attempted", False)
                and getattr(self._client, "last_refresh_invalid", False)
            )
            if not refresh_invalid:
                data["logged_in"] = True
                data["remote_status_available"] = False
                data["remote_status_message"] = "光鸭远端状态暂不可用，已保留本地登录态，稍后自动重试"
        return data

    def _save_config(self, config_payload: dict) -> Dict[str, Any]:
        try:
            config_payload = config_payload or {}
            sort_type_value = config_payload.get("sort_type")
            new_config = {
                "enabled": bool(config_payload.get("enabled", self._enabled)),
                "access_token": (config_payload.get("access_token") or self._access_token or "").strip(),
                "refresh_token": (config_payload.get("refresh_token") or self._refresh_token or "").strip(),
                "client_id": (
                    (config_payload.get("client_id") or self._client_id or GuangYaClient.DEFAULT_CLIENT_ID).strip()
                    or GuangYaClient.DEFAULT_CLIENT_ID
                ),
                "device_id": (config_payload.get("device_id") or self._device_id or "").strip(),
                "poll_interval": int(config_payload.get("poll_interval") or self._poll_interval or 5),
                "page_size": int(config_payload.get("page_size") or self._page_size or 100),
                "order_by": int(config_payload.get("order_by") or self._order_by or 3),
                "sort_type": int(self._sort_type if sort_type_value is None else sort_type_value),
                "permanently_delete": bool(config_payload.get("permanently_delete", self._permanently_delete)),
                "upload_progress_log": bool(config_payload.get("upload_progress_log", self._upload_progress_log)),
            }
            self._upload_progress_log = new_config["upload_progress_log"]
            self.update_config(new_config)
            self.init_plugin(new_config)
            return {"success": True, "message": "配置保存成功", "data": self._get_config()}
        except Exception as err:
            logger.error("【光鸭云盘助手】保存配置失败: %s", err)
            return {"success": False, "message": f"保存配置失败: {err}"}

    def get_api(self) -> List[Dict[str, Any]]:
        apis = list(super().get_api())
        for api in apis:
            path = str(api.get("path") or "")
            methods = {str(method).upper() for method in (api.get("methods") or [])}
            if path == "/config" and methods == {"GET"}:
                api["response_model"] = GuangYaConfigData
            elif path == "/config" and methods == {"POST"}:
                api["response_model"] = GuangYaConfigSaveResponse
            elif path in {"/login/qrcode", "/login/poll", "/login/logout"}:
                api["response_model"] = GuangYaActionResponse
            elif path == "/browse":
                api["response_model"] = GuangYaBrowseResponse

        apis.extend([
            {
                "path": "/login/sms/send",
                "endpoint": self.send_sms_code,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "发送光鸭云盘短信验证码",
                "response_model": GuangYaActionResponse,
            },
            {
                "path": "/login/sms/verify",
                "endpoint": self.verify_sms_login,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "校验短信验证码并完成登录",
                "response_model": GuangYaActionResponse,
            },
        ])
        apis.extend(self.get_organizer_api())
        return apis

    def _activate_storage_after_login(self) -> None:
        self._enabled = True
        config = {
            "enabled": True,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "device_id": self._device_id,
            "poll_interval": self._poll_interval,
            "page_size": self._page_size,
            "order_by": self._order_by,
            "sort_type": self._sort_type,
            "permanently_delete": self._permanently_delete,
            "upload_progress_log": self._upload_progress_log,
        }
        self.update_config(config)
        self.init_plugin(config)

    def send_sms_code(self, payload: dict) -> Dict[str, Any]:
        payload = payload or {}
        phone = str(payload.get("phone_number") or payload.get("phone") or "").strip()
        if not phone:
            return {"success": False, "stage": "moviepilot", "message": "请输入手机号"}
        if not self._client:
            self._client = GuangYaClient(
                access_token=None,
                refresh_token=None,
                client_id=self._client_id,
                device_id=self._device_id,
            )
            self._device_id = self._client.device_id
        result = self._client.request_sms_code(
            phone_number=phone,
            captcha_token=str(payload.get("captcha_token") or "").strip(),
        )
        if result.get("success"):
            self._sms_phone_number = result.get("phone_number") or phone
            self._sms_verification_id = result.get("verification_id") or ""
            self._sms_captcha_token = result.get("captcha_token") or ""
        return result

    def verify_sms_login(self, payload: dict) -> Dict[str, Any]:
        payload = payload or {}
        phone = str(payload.get("phone_number") or payload.get("phone") or self._sms_phone_number or "").strip()
        verification_id = str(payload.get("verification_id") or self._sms_verification_id or "").strip()
        captcha_token = str(payload.get("captcha_token") or self._sms_captcha_token or "").strip()
        code = str(payload.get("verification_code") or payload.get("verify_code") or "").strip()
        if not phone or not verification_id or not code:
            return {"success": False, "stage": "moviepilot", "message": "手机号、verification_id 和验证码不能为空"}
        if not captcha_token:
            return {"success": False, "stage": "moviepilot", "message": "captcha_token 已丢失，请重新获取短信验证码"}
        if not self._client:
            return {"success": False, "stage": "moviepilot", "message": "请先发送短信验证码"}
        result = self._client.signin_by_sms(
            phone_number=phone,
            verification_id=verification_id,
            verification_code=code,
            captcha_token=captcha_token,
        )
        if not result.get("success"):
            return result
        self._access_token = result.get("access_token") or ""
        self._refresh_token = result.get("refresh_token") or ""
        self._activate_storage_after_login()
        self._sms_verification_id = ""
        self._sms_phone_number = ""
        self._sms_captcha_token = ""
        return {
            "success": True,
            "message": "短信登录成功，光鸭云盘存储已启用",
            "device_id": self._device_id,
            "enabled": True,
        }

    def poll_login(self) -> Dict[str, Any]:
        if not self._device_code:
            return {"success": False, "message": "请先获取二维码", "waiting": False, "stage": "missing_device_code"}
        if self._qr_expires_at and time.time() > self._qr_expires_at:
            return {"success": False, "message": "二维码已过期，请重新获取", "waiting": False, "stage": "expired"}
        temp_client = GuangYaClient(
            access_token=None,
            refresh_token=None,
            client_id=self._client_id,
            device_id=self._device_id,
        )
        result = temp_client.poll_device_code(self._device_code) or {}
        if result.get("waiting"):
            return {
                "success": False,
                "message": result.get("message") or "等待扫码确认...",
                "waiting": True,
                "stage": result.get("stage") or "authorization_pending",
            }
        if not result.get("access_token"):
            stage = str(result.get("stage") or "device_token_error")
            message = str(result.get("message") or result.get("error_description") or result.get("error") or "光鸭未返回登录令牌")
            if str(result.get("error") or "") in {"expired_token", "access_denied", "invalid_grant"}:
                self._device_code = ""
                self._qr_expires_at = 0
            return {"success": False, "message": message, "waiting": False, "stage": stage, "upstream": result}
        self._access_token = str(result.get("access_token") or "").strip()
        self._refresh_token = str(result.get("refresh_token") or "").strip()
        if not self._access_token:
            return {"success": False, "message": "光鸭未返回 access_token", "waiting": False, "stage": "missing_access_token"}
        self._activate_storage_after_login()
        self._device_code = ""
        self._user_code = ""
        self._verification_uri = ""
        self._qr_expires_at = 0
        return {
            "success": True,
            "message": "扫码登录成功，登录信息已保存",
            "device_id": self._device_id,
            "enabled": True,
            "has_access_token": bool(self._access_token),
            "has_refresh_token": bool(self._refresh_token),
        }

    def any_files(self, fileitem: Any, extensions: list = None):
        try:
            return super().any_files(fileitem, extensions)
        except FileNotFoundError:
            logger.debug(
                "【光鸭云盘助手】【存储查询】any_files 检查时目录已不存在，按无文件处理: %s",
                str(getattr(fileitem, "path", "") or ""),
            )
            return False

    def list_files(self, fileitem: Any, recursion: bool = False):
        try:
            return super().list_files(fileitem, recursion)
        except FileNotFoundError:
            logger.debug(
                "【光鸭云盘助手】【存储查询】list_files 检查时目录已不存在，按空目录处理: %s",
                str(getattr(fileitem, "path", "") or ""),
            )
            return []

    def stop_service(self) -> None:
        self._organizer_stop()
        self._device_code = ""
        self._user_code = ""
        self._verification_uri = ""
        self._qr_expires_at = 0
        self._sms_verification_id = ""
        self._sms_phone_number = ""
        self._sms_captcha_token = ""
        self._guangya_api = None
        self._client = None
        self._enabled = False


__all__ = ["ShukGuangYaDisk"]
