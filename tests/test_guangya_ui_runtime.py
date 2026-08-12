import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v2" / "shukguangyadisk"
INIT = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
LOADER = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v111.js").read_text(encoding="utf-8")
FRONTEND_CACHE_VERSION = "1.1.1"


class GuangYaUiRuntimeTests(unittest.TestCase):
    def test_remote_entry_is_standalone(self):
        self.assertNotIn("remoteEntry_legacy.js", REMOTE)
        self.assertIn(
            f"__federation_expose_AssistantPage-v111.js?v={FRONTEND_CACHE_VERSION}",
            REMOTE,
        )
        self.assertIn(
            f"__federation_expose_AssistantConfig-dev.js?v={FRONTEND_CACHE_VERSION}",
            REMOTE,
        )

    def test_page_loader_is_fault_isolated(self):
        self.assertIn("onErrorCaptured", LOADER)
        self.assertIn("Page chunk load failed", LOADER)
        self.assertIn("重新加载", LOADER)
        self.assertIn(
            f"__federation_expose_AssistantPage-dev.js?v={FRONTEND_CACHE_VERSION}",
            LOADER,
        )

    def test_transient_network_does_not_force_logout(self):
        self.assertIn("remote_status_available", INIT)
        self.assertIn("last_refresh_invalid", INIT)
        self.assertIn('data["logged_in"] = True', INIT)
        self.assertIn("光鸭远端状态暂不可用", INIT)

    def test_versions_are_consistent(self):
        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        root_plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        runtime_version = local["version"]

        self.assertIn(f'plugin_version = "{runtime_version}"', INIT)
        self.assertEqual(package["ShukGuangYaDisk"]["version"], runtime_version)
        self.assertEqual(root_plugin["ShukGuangYaDisk"]["version"], runtime_version)


if __name__ == "__main__":
    unittest.main()
