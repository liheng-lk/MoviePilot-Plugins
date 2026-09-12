from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from source_helper import bundled_sources, physical_init_text, source_text


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


class SingleInitV391ContractTest(unittest.TestCase):
    def test_runtime_has_exactly_one_physical_python_file(self):
        python_files = sorted(path.name for path in PLUGIN.glob("*.py"))
        self.assertEqual(python_files, ["__init__.py"])
        self.assertFalse((PLUGIN / ".single_init_bundle.tmp.json").exists())

    def test_all_legacy_runtime_sources_are_embedded_and_parse(self):
        sources = bundled_sources()
        self.assertEqual(len(sources), 58)
        for required in (
            "_plugin_legacy",
            "guangya_api",
            "guangya_client",
            "storage_contract",
            "organizer",
            "organizer_state",
            "organizer_monitor_final_v390",
            "organizer_watch_pipeline_v380",
            "webdav_provider",
        ):
            self.assertIn(required, sources)
        for name, source in sources.items():
            ast.parse(source, filename=f"embedded:{name}.py")

    def test_single_init_wrapper_parses_and_hot_reload_is_fenced(self):
        physical = physical_init_text()
        ast.parse(physical)
        self.assertIn("_GuangYaBundledFinder", physical)
        self.assertIn("_bundle_sys.modules.pop", physical)
        self.assertIn("_guangya_bundle_package", physical)
        self.assertIn("linecache", physical)
        self.assertIn('runtime_layout = "single-init-bundled"', physical)

    def test_registration_api_is_static_and_does_not_call_super(self):
        tree = ast.parse(physical_init_text())
        target = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_single_init_get_organizer_api"
        )
        calls = [
            node for node in ast.walk(target)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_organizer_api"
        ]
        self.assertEqual(calls, [])
        source = ast.get_source_segment(physical_init_text(), target) or ""
        self.assertIn('"/organize/monitor/status"', source)
        self.assertIn('"/organize/monitor/full-scan"', source)

    def test_legacy_entry_mro_and_final_monitor_are_preserved(self):
        entry = source_text("__init__.py")
        self.assertIn('plugin_version = "3.9.1"', entry)
        class_slice = entry.split("class ShukGuangYaDisk(", 1)[1].split("):", 1)[0]
        self.assertLess(
            class_slice.index("_GuangYaFinalMonitorV390Mixin"),
            class_slice.index("_GuangYaOrganizerMonitorV366Mixin"),
        )
        final_monitor = source_text("organizer_monitor_final_v390.py")
        self.assertIn("def organize_monitor_tick", final_monitor)
        self.assertIn("_v390_dispatch_one", final_monitor)

    def test_release_metadata_and_federation_cache_are_consistent(self):
        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
        remote = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")
        self.assertEqual(local["version"], "3.9.1")
        self.assertEqual(package["version"], "3.9.1")
        self.assertIn("v3.9.1", local["history"])
        self.assertIn("?v=3.9.1", remote)


if __name__ == "__main__":
    unittest.main()
