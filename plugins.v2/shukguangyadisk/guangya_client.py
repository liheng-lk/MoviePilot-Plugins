"""光鸭云盘 HTTP 客户端兼容层。

文件 API 继续复用原实现；扫码登录严格沿用 KoWming 当前可用实现，
短信登录参考 DDSRem-Dev/guangyaclient 当前实现。
"""

import time
from secrets import token_hex
from typing import Any, Dict, Optional

from app.log import logger

from .guangya_client_legacy import GuangYaClient as _LegacyGuangYaClient


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

    def get_device_code(self) -> Optional[Dict[str, Any]]:
        """获取设备码与二维码：严格沿用 KoWming 当前可用实现。"""
        result = self._request(
            method="POST",
            url=f"{self.ACCOUNT_BASE_URL}/v1/auth/device/code",
            data={
                "scope": "user",
                "client_id": self._client_id,
            },
            need_auth=False,
        )
        if result.get("error"):
            return None
        return result

    def poll_device_code(self, device_code: str) -> Optional[Dict[str, Any]]:
        """轮询设备码状态：严格沿用 KoWming 当前可用实现。"""
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
            if self._on_token_refresh:
                try:
                    self._on_token_refresh(self._access_token, self._refresh_token)
                except Exception:
                    pass
            return result
        return None

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
