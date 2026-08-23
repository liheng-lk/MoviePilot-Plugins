"""MoviePilot V3 自定义存储模块合同。

V3 的 StorageChain 会优先通过插件 ``get_module()`` 调用 ``storage_manage``。
如果插件没有实现该方法，请求会继续落到宿主 FileManager，而宿主只认识内置
StorageBase，因此自定义存储会得到“Unsupported storage type”。本 mixin 把光鸭
插件自己的存储能力显式接入 V3 的模块调度器。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


class V3StorageContractMixin:
    """为光鸭自定义存储补齐 MoviePilot V3 的模块合同。"""

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

    def _v3_storage_helper(self):
        """延迟导入稳定 SDK，便于脱离 MoviePilot 宿主做合同单测。"""
        from app.sdk.services import StorageHelper

        return StorageHelper()

    def get_module(self) -> Dict[str, Any]:
        """在原文件操作模块之上增加 V3 存储管理入口。"""
        modules = dict(super().get_module() or {})
        modules["storage_manage"] = self.storage_manage
        modules["get_folder"] = self.get_folder
        return modules

    def get_folder(self, storage: str, path: Path):
        """适配 V3 ``StorageChain.get_folder(storage, path)`` 签名。"""
        if storage != self._disk_name:
            return None
        if not self._guangya_api:
            return None
        return self._guangya_api.get_folder(path)

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
        """处理 MoviePilot V3 网盘存储统一管理动作。

        对其它存储返回 ``None``，允许模块调度器继续交给宿主 FileManager；对光鸭
        始终返回明确结果，从而阻止宿主把自定义存储误判为“不支持的存储类型”。
        """
        if storage != self._disk_name:
            return None

        action_name = self._action_name(action)

        if action_name == "support_transtype":
            return {
                "success": True,
                "message": "",
                "data": {"transtype": self.support_transtype(storage) or {}},
            }

        if action_name == "usage":
            if not self._guangya_api:
                return {
                    "success": False,
                    "message": "光鸭云盘助手尚未初始化或未登录",
                    "data": {},
                }
            try:
                usage = self.storage_usage(storage)
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
