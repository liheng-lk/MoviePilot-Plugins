import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = ROOT / "plugins.v3"

PLUGIN_ENTRIES = (
    PLUGIN_ROOT / "dailyassistant" / "__init__.py",
    PLUGIN_ROOT / "dailynewdrama" / "__init__.py",
    PLUGIN_ROOT / "guangyatransferassistant" / "__init__.py",
    PLUGIN_ROOT / "shukguangyadisk" / "__init__.py",
)

def _decoded_source_text(path: Path) -> str:
    """Decode imports embedded in the two single-file plugin bundles."""
    return (
        path.read_text(encoding="utf-8")
        .replace("\\\\n", "\n")
        .replace("\\n", "\n")
    )


class OfficialPluginSdkContractTests(unittest.TestCase):
    """Keep V3 imports aligned with the official MoviePilot plugin contract."""

    def test_all_v3_plugin_bases_use_official_public_entry(self):
        for entry in PLUGIN_ENTRIES:
            with self.subTest(entry=entry):
                source = _decoded_source_text(entry)
                self.assertIn("from app.plugins import _PluginBase", source)
                self.assertNotIn("from app.sdk.plugin import _PluginBase", source)

    def test_all_plugin_managers_use_official_plural_sdk_entry(self):
        for entry in PLUGIN_ENTRIES:
            with self.subTest(entry=entry):
                source = _decoded_source_text(entry)
                self.assertNotIn("from app.sdk.plugin import PluginManager", source)
                if "PluginManager" in source:
                    self.assertIn("from app.sdk.plugins import PluginManager", source)

    def test_v2_source_keeps_its_documented_public_base_entry(self):
        source = (ROOT / "plugins.v2" / "dailynewdrama" / "__init__.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from app.plugins import _PluginBase", source)
        self.assertNotIn("from app.sdk.plugin import _PluginBase", source)


if __name__ == "__main__":
    unittest.main()
