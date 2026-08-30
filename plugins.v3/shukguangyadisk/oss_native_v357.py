"""v3.5.7：仅依赖 MoviePilot 自带 requests 的 OSS STS 分片上传。

V3 插件不再安装 oss2。这里直接实现 OSS REST Multipart Upload 的最小合同：
InitiateMultipartUpload -> UploadPart -> CompleteMultipartUpload；失败时 Abort。

鉴权使用 OSS V1 Header Signature。光鸭返回的是 STS 临时凭证，因此
``x-oss-security-token`` 既发送到 OSS，也参与 CanonicalizedOSSHeaders。
"""

from __future__ import annotations

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
