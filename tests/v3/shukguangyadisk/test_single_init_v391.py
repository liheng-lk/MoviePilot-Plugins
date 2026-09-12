from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from source_helper import bundled_sources, physical_init_text, source_text


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"


class SingleInitV3910ContractTest(unittest.TestCase):
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
        self.assertIn('"/organize/monitor/graceful-stop"', source)

    def test_runtime_version_projection_is_dynamic_and_hot_reload_is_observable(self):
        physical = physical_init_text()
        self.assertIn('"runtime_version": str(getattr(self, "plugin_version", "") or "")', physical)
        self.assertIn('"runtime_bundle_module_count": len(_BUNDLED_SOURCES)', physical)
        self.assertIn('"runtime_loaded_bundle_module_count": loaded_bundle_modules', physical)
        self.assertIn('"runtime_finder_count": finder_count', physical)
        self.assertIn('"runtime_hot_reload_fence_ok": finder_count == 1', physical)
        self.assertNotIn('"runtime_version": "3.9.2"', physical)

    def test_v3_sdk_boundaries_do_not_regress_to_legacy_imports(self):
        sources = bundled_sources()
        forbidden = (
            "from app.log import logger",
            "from app.core.config import",
            "from app.core.event import",
            "from app.helper.storage import",
            "from app.runtime.config import global_vars",
            "from app.runtime.events import",
            "from app.domain.meta.metabase import MetaBase",
            "from app.domain.metainfo import MetaInfo",
            "from app.application.scheduling import update_plugin_job",
            "from app.modules.themoviedb.category import CategoryHelper",
        )
        combined = "\n".join(sources.values())
        for marker in forbidden:
            self.assertNotIn(marker, combined)
        category = sources["organizer_category_consistency_v3412"]
        self.assertIn("from app.sdk.classification import classify_media", category)
        self.assertIn("classified = classify_media(media)", category)

        legacy_pending = [
            name
            for name, source in sources.items()
            if "from app.db.transferpending_oper import TransferPendingOper" in source
        ]
        self.assertEqual(
            legacy_pending,
            ["organizer_legacy_queue_cleanup_v343", "organizer_queue_recovery"],
        )

    def test_webdav_put_uses_defined_existing_item_for_status(self):
        source = source_text("webdav_provider.py")
        put = source.split("def _handle_put", 1)[1].split("def _handle_move", 1)[0]
        self.assertIn("existing_item = self._api.get_item(PathLib(path))", put)
        self.assertIn("status_code=201 if existing_item is None else 204", put)
        self.assertNotIn("if not item else 204", put)

    def test_legacy_entry_mro_and_final_monitor_are_preserved(self):
        entry = source_text("__init__.py")
        self.assertIn('plugin_version = "3.9.10"', entry)
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
        self.assertEqual(local["version"], "3.9.10")
        self.assertEqual(package["version"], "3.9.10")
        self.assertIn("v3.9.10", local["history"])
        self.assertIn("?v=3.9.10", remote)


if __name__ == "__main__":
    unittest.main()
