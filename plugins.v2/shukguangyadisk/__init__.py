"""光鸭云盘助手插件入口。

认证逻辑沿用已验证实现；存储名称统一为“光鸭云盘助手”，并提供可选上传进度监控。
同时在入口层统一 legacy 模块日志前缀，避免旧名称混杂。
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from app.db.systemconfig_oper import SystemConfigOper
from app.helper.storage import StorageHelper
from app.log import logger
from app.schemas.types import SystemConfigKey

from ._plugin_legacy import ShukGuangYaDisk as _LegacyPlugin
from .guangya_client import GuangYaClient



class ShukGuangYaDisk(_LegacyPlugin):
    """光鸭云盘助手。"""

    plugin_name = "光鸭云盘助手"
    plugin_desc = "MoviePilot 光鸭云盘存储助手，支持扫码/短信登录、目录浏览、整理上传、下载、移动、复制和 Emby 直连。"
    plugin_version = "1.1"
    plugin_author = "liheng-lk"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"

    _disk_name = "光鸭云盘助手"
    _legacy_disk_name = "Shuk-光鸭云盘"
    _upload_progress_log: bool = False

    _sms_verification_id: str = ""
    _sms_phone_number: str = ""
    _sms_captcha_token: str = ""

    def _migrate_storage_name(self) -> None:
        """将旧存储名称迁移为当前插件名称，并清理重复项。"""
        try:
            storages = StorageHelper().get_storagies()
            if not storages:
                return
            changed = False
            new_exists = any(s.type == self._disk_name for s in storages)
            migrated = []
            for storage in storages:
                if storage.type == self._legacy_disk_name:
                    changed = True
                    if new_exists:
                        continue
                    storage.type = self._disk_name
                    storage.name = self._disk_name
                    new_exists = True
                elif storage.type == self._disk_name and storage.name != self._disk_name:
                    storage.name = self._disk_name
                    changed = True
                migrated.append(storage)
            if changed:
                SystemConfigOper().set(
                    SystemConfigKey.Storages,
                    [item.model_dump() for item in migrated],
                )
                logger.info("【光鸭云盘助手】MoviePilot 存储名称已迁移为: %s", self._disk_name)
        except Exception as err:
            logger.warning("【光鸭云盘助手】迁移存储名称失败: %s", err)

    def init_plugin(self, config: dict = None) -> None:
        """初始化插件，并把上传日志开关同步到存储适配器。"""
        config = config or {}
        if "upload_progress_log" in config:
            self._upload_progress_log = bool(config.get("upload_progress_log"))
        self._migrate_storage_name()
        super().init_plugin(config)
        if self._guangya_api:
            self._guangya_api.upload_progress_log = self._upload_progress_log

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue Federation 模式下仅提供初始配置。"""
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
        """读取配置，并补充上传监控与当前存储名称。"""
        data = super()._get_config()
        data["upload_progress_log"] = self._upload_progress_log
        data["storage_name"] = self._disk_name
        return data

    def _save_config(self, config_payload: dict) -> Dict[str, Any]:
        """保存配置，包括上传进度监控开关。"""
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
        """返回插件 API。"""
        apis = list(super().get_api())
        apis.extend([
            {
                "path": "/login/sms/send",
                "endpoint": self.send_sms_code,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "发送光鸭云盘短信验证码",
            },
            {
                "path": "/login/sms/verify",
                "endpoint": self.verify_sms_login,
                "auth": "bear",
                "methods": ["POST"],
                "summary": "校验短信验证码并完成光鸭云盘登录",
            },
        ])
        return apis

    def _activate_storage_after_login(self) -> None:
        """登录成功后启用并重新初始化存储适配器。"""
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
        """发送短信验证码。"""
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
        """校验短信验证码并完成登录。"""
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
        """轮询扫码登录状态并保存 Token。"""
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
        result = temp_client.poll_device_code(self._device_code)
        if result and result.get("waiting"):
            return {
                "success": False,
                "message": result.get("message") or "等待扫码确认...",
                "waiting": True,
                "stage": "authorization_pending",
            }
        if not result or not result.get("access_token"):
            return {
                "success": False,
                "message": "已扫码，等待光鸭返回登录令牌...",
                "waiting": True,
                "stage": "token_pending",
            }

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


__all__ = ["ShukGuangYaDisk"]
