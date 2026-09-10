from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


class ComponentLoaderV381Test(unittest.TestCase):
    def test_remote_entry_uses_fresh_v381_chunk(self):
        remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
        self.assertIn("__federation_expose_AssistantPage-v381.js", remote)
        self.assertNotIn("__federation_expose_AssistantPage-v376.js?v=3.8.0", remote)
        self.assertTrue((PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v381.js").exists())

    def test_v381_control_surface_and_base_page_are_present(self):
        page = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v381.js").read_text(encoding="utf-8")
        self.assertIn("__federation_expose_AssistantPage-v352.js?v=3.7.6", page)
        for label in ("增量观察一次", "强制全量巡检", "停止全量巡检", "刷新状态"):
            self.assertIn(label, page)
        for endpoint in (
            "/organize/monitor/incremental-scan",
            "/organize/monitor/full-scan",
            "/organize/monitor/full-scan/stop",
            "/organize/monitor/status",
        ):
            self.assertIn(endpoint, page)

    def test_release_version_is_consistent(self):
        init_text = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        plugin_json = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        package_json = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        self.assertIn('plugin_version = "3.8.1"', init_text)
        self.assertEqual(plugin_json["version"], "3.8.1")
        self.assertEqual(package_json["ShukGuangYaDisk"]["version"], "3.8.1")


if __name__ == "__main__":
    unittest.main()
