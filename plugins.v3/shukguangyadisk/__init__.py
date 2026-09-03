"""光鸭云盘助手 MoviePilot V3 插件入口。

V3 版本保留已验证的光鸭认证、存储和上传实现，只在宿主边界使用 V3 稳定 SDK、
明确 API 响应模型，并补齐可重复的生命周期清理。
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger
from app.sdk.services import StorageHelper

from . import _plugin_legacy as _legacy_module
from .guangya_api_v112 import GuangYaApi as _StableGuangYaApi
from .guangya_client import GuangYaClient
from .models import (
    GuangYaActionResponse,
    GuangYaBrowseResponse,
    GuangYaConfigData,
    GuangYaConfigSaveResponse,
)
# 先完整加载纯历史层，再加载 v3.6 Engine。旧 orchestrator 在 Engine 导入期间会反向引用
# organizer_folder_history；此顺序确保引用的是已经定义完成的类，避免循环导入。
from .organizer_folder_history import GuangYaFolderHistoryMixin
from .organizer_execution_v360 import GuangYaOrganizerExecutionV360Mixin
from .organizer_pending_revisit_v361 import GuangYaOrganizerPendingRevisitV361Mixin
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin
from .organizer_worker_guard import GuangYaWorkerGuardMixin
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_candidate_filter import GuangYaCandidateFilterMixin
from .organizer_folder_stream import GuangYaFolderStreamMixin
from .organizer_recognition import GuangYaOrganizerMixin
from .storage_contract import V3StorageContractMixin

_legacy_module.GuangYaApi = _StableGuangYaApi
_LegacyPlugin = _legacy_module.ShukGuangYaDisk


class ShukGuangYaDisk(
    # v3.6.6 必须位于最前：最终控制真实 interval、资源增量发现、目录批量准入边界与
    # admission conflict；v3.6.1 继续提供稳定等待 pending 回访，其余兼容层不抢占调度权。
    GuangYaOrganizerMonitorV366Mixin,
    GuangYaOrganizerPendingRevisitV361Mixin,
    GuangYaOrganizerExecutionV360Mixin,
    GuangYaFolderHistoryMixin,
    GuangYaWorkerGuardMixin,
    GuangYaQueueRecoveryMixin,
    GuangYaCandidateFilterMixin,
    GuangYaFolderStreamMixin,
    GuangYaOrganizerMixin,
    V3StorageContractMixin,
    _LegacyPlugin,
):
    """光鸭云盘助手 MoviePilot V3 专用实现。"""

    plugin_name = "光鸭云盘助手"
    plugin_desc = "MoviePilot V3 光鸭云盘存储助手，支持自动整理、目录监控、上传、WebDAV 与 Emby。"
    plugin_version = "3.6.7"
    plugin_author = "liheng-lk"
    plugin_label = "存储,光鸭云盘,自动整理,目录监控,MoviePilot,挂载,Emby,WebDAV"
    author_url = "https://github.com/liheng-lk/MoviePilot-Plugins"

    _disk_name = "光鸭云盘助手"
    _legacy_disk_name = "Shuk-光鸭云盘"
    _upload_progress_log: bool = False

    _sms_verification_id: str = ""
    _sms_phone_number: str = ""
    _sms_captcha_token: str = ""

    def _migrate_storage_name(self) -> None:
        """V3 通过稳定 StorageHelper 确保当前存储已注册，不直接写宿主配置表。"""
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
            if any(storage.type == self._legacy_disk_name for storage in storages):
                logger.info("【光鸭云盘助手】检测到历史存储名称 %s；V3 使用当前存储 %s，不直接修改宿主内部配置", self._legacy_disk_name, self._disk_name)
        except Exception as err:
            logger.warning("【光鸭云盘助手】V3 存储注册检查失败: %s", err)

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
        """读取配置；临时网络异常时保留本地登录态。"""
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
        """保存账号与存储配置。自动整理设置由独立后端持久化接口保存。"""
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
        """返回 V3 插件 API，并为普通 JSON 端点声明明确响应模型。"""
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

    def stop_service(self) -> None:
        """释放运行时客户端和临时登录状态；不修改用户持久化配置。"""
        self._device_code = ""
        self._user_code = ""
        self._verification_uri = ""
        self._qr_expires_at = 0
        self._sms_verification_id = ""
        self._sms_phone_number = ""
        self._sms_captcha_token = ""
        if self._organize_dispatcher:
            try:
                self._organize_dispatcher.clear_pending()
            except Exception as err:
                logger.debug("【光鸭云盘助手】【自动整理】清理 MP dispatcher pending 失败: %s", err)
        self._organize_dispatcher = None
        self._organize_state_store = None
        self._organize_monitor_initialized = False
        self._guangya_api = None
        self._client = None
        self._enabled = False


__all__ = ["ShukGuangYaDisk"]
