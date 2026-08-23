from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins.v3" / "shukguangyadisk" / "storage_contract.py"
spec = importlib.util.spec_from_file_location("shukguangyadisk_storage_contract", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)
V3StorageContractMixin = module.V3StorageContractMixin


class FakeModel:
    def __init__(self, **data):
        self.data = data

    def model_dump(self):
        return dict(self.data)


class FakeApi:
    def __init__(self):
        self.paths = []

    def get_folder(self, path):
        self.paths.append(path)
        return {"path": str(path), "type": "dir"}

    def get_item(self, path):
        return {"path": str(path), "type": "dir"}


class FakeStorageHelper:
    def __init__(self):
        self.saved = None
        self.reset = None

    def get_storage(self, storage):
        return FakeModel(type=storage, name=storage, config={})

    def set_storage(self, storage, conf):
        self.saved = (storage, conf)

    def reset_storage(self, storage):
        self.reset = storage


class FakeBase:
    def get_module(self):
        return {"list_files": lambda *args, **kwargs: []}


class FakePlugin(V3StorageContractMixin, FakeBase):
    _disk_name = "光鸭云盘助手"

    def __init__(self):
        self._enabled = True
        self._guangya_api = FakeApi()
        self.helper = FakeStorageHelper()

    def _v3_storage_helper(self):
        return self.helper

    def support_transtype(self, storage):
        return {"move": "移动", "copy": "复制"} if storage == self._disk_name else None

    def storage_usage(self, storage):
        return FakeModel(total=1000, used=250, free=750)

    def get_qrcode(self):
        return {"success": True, "message": "", "user_code": "123456"}

    def poll_login(self):
        return {"success": False, "message": "等待扫码", "waiting": True}

    def logout(self):
        return {"success": True, "message": "已退出登录"}


class StorageContractTest(unittest.TestCase):
    def setUp(self):
        self.plugin = FakePlugin()

    def test_get_module_registers_v3_management_and_folder_contracts(self):
        modules = self.plugin.get_module()
        self.assertIn("list_files", modules)
        self.assertIs(modules["storage_manage"].__self__, self.plugin)
        self.assertIs(modules["get_folder"].__self__, self.plugin)

    def test_other_storage_falls_through(self):
        self.assertIsNone(self.plugin.storage_manage("local", "usage"))

    def test_support_transtype_is_handled_by_plugin(self):
        result = self.plugin.storage_manage("光鸭云盘助手", "support_transtype")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["transtype"], {"move": "移动", "copy": "复制"})

    def test_usage_is_handled_by_plugin(self):
        result = self.plugin.storage_manage("光鸭云盘助手", "usage")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"total": 1000, "used": 250, "free": 750})

    def test_get_folder_matches_v3_storage_chain_signature(self):
        result = self.plugin.get_folder("光鸭云盘助手", Path("/媒体/电视剧"))
        self.assertEqual(result["path"], "/媒体/电视剧")
        self.assertIsNone(self.plugin.get_folder("local", Path("/tmp")))

    def test_save_and_reset_config_do_not_fall_into_system_filemanager(self):
        save = self.plugin.storage_manage("光鸭云盘助手", "save_config", conf={"foo": "bar"})
        self.assertTrue(save["success"])
        self.assertEqual(self.plugin.helper.saved, ("光鸭云盘助手", {"foo": "bar"}))
        reset = self.plugin.storage_manage("光鸭云盘助手", "reset_config")
        self.assertTrue(reset["success"])
        self.assertEqual(self.plugin.helper.reset, "光鸭云盘助手")

    def test_unknown_action_returns_plugin_error_not_host_unsupported_storage(self):
        result = self.plugin.storage_manage("光鸭云盘助手", "future_action")
        self.assertFalse(result["success"])
        self.assertIn("暂不支持存储管理动作", result["message"])
        self.assertNotIn("不支持的存储类型", result["message"])

    def test_qrcode_and_login_actions_use_unified_envelope(self):
        qr = self.plugin.storage_manage("光鸭云盘助手", "generate_qrcode")
        self.assertTrue(qr["success"])
        self.assertEqual(qr["data"]["user_code"], "123456")
        poll = self.plugin.storage_manage("光鸭云盘助手", "check_login")
        self.assertFalse(poll["success"])
        self.assertEqual(poll["message"], "等待扫码")


if __name__ == "__main__":
    unittest.main()
