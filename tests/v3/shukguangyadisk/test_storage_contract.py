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


class FakeFileItem:
    def __init__(self, storage: str, path: str = "/媒体/电视剧"):
        self.storage = storage
        self.path = path

    def model_copy(self, update=None):
        update = update or {}
        return FakeFileItem(
            storage=update.get("storage", self.storage),
            path=update.get("path", self.path),
        )


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
        return {
            "list_files": self.list_files,
            "upload_file": self.upload_file,
            "storage_usage": self.base_storage_usage,
        }

    def list_files(self, fileitem, recursion=False):
        return [fileitem.storage, recursion]

    def upload_file(self, fileitem, path, new_name=None):
        return {"storage": fileitem.storage, "path": str(path), "new_name": new_name}

    def base_storage_usage(self, storage):
        return {"storage": storage}


class FakePlugin(V3StorageContractMixin, FakeBase):
    _disk_name = "光鸭云盘助手"
    _legacy_disk_name = "Shuk-光鸭云盘"

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


class FakeEventData:
    def __init__(self, storage):
        self.storage = storage
        self.storage_oper = None


class FakeEvent:
    def __init__(self, storage):
        self.event_data = FakeEventData(storage)


class StorageContractTest(unittest.TestCase):
    def setUp(self):
        self.plugin = FakePlugin()

    def test_get_module_registers_v3_management_and_folder_contracts(self):
        modules = self.plugin.get_module()
        self.assertIn("list_files", modules)
        self.assertIn("upload_file", modules)
        self.assertIs(modules["storage_manage"].__self__, self.plugin)
        self.assertIs(modules["get_folder"].__self__, self.plugin)

    def test_other_storage_falls_through(self):
        self.assertIsNone(self.plugin.storage_manage("local", "usage"))

    def test_support_transtype_is_handled_by_plugin(self):
        result = self.plugin.storage_manage("光鸭云盘助手", "support_transtype")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["transtype"], {"move": "移动", "copy": "复制"})

    def test_legacy_storage_name_is_short_circuited_by_plugin(self):
        result = self.plugin.storage_manage("Shuk-光鸭云盘", "support_transtype")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["transtype"], {"move": "移动", "copy": "复制"})
        self.assertNotIn("不支持的存储类型", result["message"])

    def test_usage_is_handled_by_plugin(self):
        result = self.plugin.storage_manage("光鸭云盘助手", "usage")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"total": 1000, "used": 250, "free": 750})

    def test_legacy_storage_name_is_normalized_for_module_handlers(self):
        modules = self.plugin.get_module()
        item = FakeFileItem("Shuk-光鸭云盘")
        listed = modules["list_files"](item, recursion=True)
        self.assertEqual(listed, ["光鸭云盘助手", True])
        uploaded = modules["upload_file"](item, Path("/tmp/demo.mkv"), "demo.mkv")
        self.assertEqual(uploaded["storage"], "光鸭云盘助手")
        usage = modules["storage_usage"]("Shuk-光鸭云盘")
        self.assertEqual(usage, {"storage": "光鸭云盘助手"})
        self.assertEqual(item.storage, "Shuk-光鸭云盘")

    def test_get_folder_matches_v3_storage_chain_signature(self):
        result = self.plugin.get_folder("光鸭云盘助手", Path("/媒体/电视剧"))
        self.assertEqual(result["path"], "/媒体/电视剧")
        legacy = self.plugin.get_folder("Shuk-光鸭云盘", Path("/媒体/旧任务"))
        self.assertEqual(legacy["path"], "/媒体/旧任务")
        self.assertIsNone(self.plugin.get_folder("local", Path("/tmp")))

    def test_legacy_storage_selection_event_returns_guangya_operator(self):
        event = FakeEvent("Shuk-光鸭云盘")
        self.plugin.storage_oper_selection(event)
        self.assertIs(event.event_data.storage_oper, self.plugin._guangya_api)

    def test_save_and_reset_config_do_not_fall_into_system_filemanager(self):
        save = self.plugin.storage_manage("Shuk-光鸭云盘", "save_config", conf={"foo": "bar"})
        self.assertTrue(save["success"])
        self.assertEqual(self.plugin.helper.saved, ("光鸭云盘助手", {"foo": "bar"}))
        reset = self.plugin.storage_manage("Shuk-光鸭云盘", "reset_config")
        self.assertTrue(reset["success"])
        self.assertEqual(self.plugin.helper.reset, "光鸭云盘助手")

    def test_unknown_action_returns_plugin_error_not_host_unsupported_storage(self):
        result = self.plugin.storage_manage("Shuk-光鸭云盘", "future_action")
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
