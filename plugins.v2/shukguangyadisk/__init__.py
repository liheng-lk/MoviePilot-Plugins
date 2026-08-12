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
            "page_size": self._page_size,
            "order_by": self._order_by,
            "sort_type": self._sort_type,
            "webdav_enable": self._webdav_enable,
            "permanently_delete": self._permanently_delete,
            "upload_progress_log": self._upload_progress_log,
        }

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明插件使用 Vue Federation 组件渲染。"""
        return "vue", "dist/assets"

    def _on_token_refresh(self, access_token: str, refresh_token: str) -> None:
        """刷新 token 后立即写回插件配置。"""
        old_access = self._access_token
        old_refresh = self._refresh_token
        self._access_token = access_token
        self._refresh_token = refresh_token
        logger.info(
            "【光鸭云盘助手】收到 Token 刷新回调: access_token=%s, refresh_token=%s, old_access_token=%s, old_refresh_token=%s",
            GuangYaClient._mask_token(self._access_token),
            GuangYaClient._mask_token(self._refresh_token),
            GuangYaClient._mask_token(old_access),
            GuangYaClient._mask_token(old_refresh),
        )
        self._save_current_config()

    def _save_current_config(self) -> None:
        """保存当前运行配置。"""
        config = {
            "enabled": self._enabled,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
            "device_id": self._device_id,
            "page_size": self._page_size,
            "order_by": self._order_by,
            "sort_type": self._sort_type,
            "webdav_enable": self._webdav_enable,
            "permanently_delete": self._permanently_delete,
            "upload_progress_log": self._upload_progress_log,
        }
        logger.info(
            "【光鸭云盘助手】准备回写配置: device_id=%s, access_token=%s, refresh_token=%s",
            self._device_id,
            GuangYaClient._mask_token(self._access_token),
            GuangYaClient._mask_token(self._refresh_token),
        )
        self.update_config(config)
        logger.info("【光鸭云盘助手】Token 已自动保存")

    def stop_service(self) -> None:
        """停止插件服务。"""
        super().stop_service()

    def _wait_for_client(self, retries: int = 20, interval: float = 0.2) -> bool:
        """等待光鸭客户端初始化完成。"""
        for _ in range(retries):
            if self._guangya_client:
                return True
            time.sleep(interval)
        return False
