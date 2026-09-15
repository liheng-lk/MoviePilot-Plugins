from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = ROOT / "plugins.v3"

PLUGIN_ENTRIES = (
    PLUGIN_ROOT / "dailyassistant" / "__init__.py",
    PLUGIN_ROOT / "dailynewdrama" / "__init__.py",
    PLUGIN_ROOT / "guangyatransferassistant" / "__init__.py",
    PLUGIN_ROOT / "shukguangyadisk" / "__init__.py",
)

BASE_DUAL_IMPORT = (
    "try:\n"
    "    from app.sdk.plugin import _PluginBase\n"
    "except ImportError:\n"
    "    from app.plugins import _PluginBase"
)
MANAGER_DUAL_IMPORT = (
    "try:\n"
    "    from app.sdk.plugin import PluginManager\n"
    "except ImportError:\n"
    "    from app.sdk.plugins import PluginManager"
)


def _decoded_source_text(path: Path) -> str:
    """Match imports in normal modules and JSON-escaped single-file bundles."""
    return (
        path.read_text(encoding="utf-8")
        .replace("\\\\n", "\n")
        .replace("\\n", "\n")
    )


def test_all_v3_plugin_bases_prefer_new_sdk_with_legacy_fallback():
    for entry in PLUGIN_ENTRIES:
        source = _decoded_source_text(entry)
        assert BASE_DUAL_IMPORT in source, entry
        assert source.count("from app.plugins import _PluginBase") == source.count(
            BASE_DUAL_IMPORT
        ), entry


def test_all_v3_plugin_managers_prefer_new_sdk_with_legacy_fallback():
    for entry in PLUGIN_ENTRIES:
        source = _decoded_source_text(entry)
        legacy_count = source.count("from app.sdk.plugins import PluginManager")
        if not legacy_count:
            continue
        assert source.count(MANAGER_DUAL_IMPORT) == legacy_count, entry


def test_v2_sources_are_not_part_of_the_sdk_migration():
    v2_source = (ROOT / "plugins.v2" / "dailynewdrama" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "from app.plugins import _PluginBase" in v2_source
    assert "from app.sdk.plugin import _PluginBase" not in v2_source
