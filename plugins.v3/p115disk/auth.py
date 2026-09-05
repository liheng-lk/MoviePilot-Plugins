"""115 二维码登录。

使用 115 公开扫码端点，避免 ``P115Client(None)`` 在 MoviePilot 后台进入交互式
控制台扫码。二维码状态由插件 API 主动轮询，登录成功后只持久化 Cookie。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
STATUS_URL = "https://qrcodeapi.115.com/get/status/"
PASSPORT_URL = "https://passportapi.115.com/app/1.0/{app}/1.0/login/qrcode/"


@dataclass(slots=True)
class QrToken:
    uid: str
    time: str
    sign: str
    qrcode: str

    def public_dict(self) -> Dict[str, str]:
        return {
            "uid": self.uid,
            "time": self.time,
            "sign": self.sign,
            "qrcode": self.qrcode,
        }


def _request_json(url: str, *, data: dict | None = None, timeout: int = 15) -> Dict[str, Any]:
    body = urlencode(data).encode("utf-8") if data is not None else None
    request = Request(
        url,
        data=body,
        method="POST" if data is not None else "GET",
        headers={"User-Agent": "Mozilla/5.0 MoviePilot-P115/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("115 登录接口返回格式异常")
    return payload


def create_qr_token() -> QrToken:
    resp = _request_json(TOKEN_URL)
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    uid = str(data.get("uid") or "")
    timestamp = str(data.get("time") or "")
    sign = str(data.get("sign") or "")
    qrcode = str(data.get("qrcode") or "")
    if not uid or not timestamp or not sign or not qrcode:
        raise RuntimeError(str(resp.get("message") or resp.get("error") or "115 二维码令牌获取失败"))
    return QrToken(uid=uid, time=timestamp, sign=sign, qrcode=qrcode)


def poll_qr_status(token: QrToken) -> Dict[str, Any]:
    query = urlencode({"uid": token.uid, "time": token.time, "sign": token.sign})
    return _request_json(f"{STATUS_URL}?{query}")


def exchange_qr_cookie(uid: str, *, app: str = "qandroid") -> Dict[str, Any]:
    app = str(app or "qandroid").strip()
    return _request_json(
        PASSPORT_URL.format(app=app),
        data={"app": app, "account": str(uid)},
    )


def extract_cookie(resp: Dict[str, Any]) -> str:
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    candidates = [data.get("cookie"), data.get("cookies"), resp.get("cookie"), resp.get("cookies")]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip(";")
        if isinstance(value, dict) and value:
            parts = [f"{key}={item}" for key, item in value.items() if item is not None and str(item) != ""]
            if parts:
                return "; ".join(parts)
    raise RuntimeError(str(resp.get("message") or resp.get("error") or "扫码成功但未取得 Cookie"))
