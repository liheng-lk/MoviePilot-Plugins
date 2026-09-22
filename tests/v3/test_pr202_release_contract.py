import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET_VERSIONS = {
    "DailyAssistant": "1.3.9",
    "DailyNewDrama": "3.0.2",
    "ShukGuangYaDisk": "3.9.27",
    "GuangYaTransferAssistant": "2.1.10",
}


def _physical_version(plugin_id: str) -> str | None:
    path = ROOT / "plugins.v3" / plugin_id.lower() / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != plugin_id:
            continue
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "plugin_version"
                for target in statement.targets
            ):
                continue
            if isinstance(statement.value, ast.Constant):
                return str(statement.value.value)
    return None


class Pr202ReleaseContractTests(unittest.TestCase):
    def test_four_plugins_publish_new_consistent_versions(self):
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        for plugin_id, expected in TARGET_VERSIONS.items():
            with self.subTest(plugin_id=plugin_id):
                metadata = package[plugin_id]
                self.assertEqual(expected, metadata["version"])
                self.assertEqual(expected, _physical_version(plugin_id))
                self.assertEqual(f"v{expected}", next(iter(metadata["history"])))
                self.assertIs(metadata.get("release"), True)

                plugin_json = ROOT / "plugins.v3" / plugin_id.lower() / "plugin.json"
                if plugin_json.is_file():
                    manifest = json.loads(plugin_json.read_text(encoding="utf-8"))
                    self.assertEqual(expected, manifest["version"])


if __name__ == "__main__":
    unittest.main()
