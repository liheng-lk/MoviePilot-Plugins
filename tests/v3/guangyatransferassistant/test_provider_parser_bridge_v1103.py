from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PROVIDER = PLUGIN / "provider_reliability_v1100.py"
CONSOLE = PLUGIN / "console_ui_v1100.py"

provider_text = PROVIDER.read_text(encoding="utf-8")
console_text = CONSOLE.read_text(encoding="utf-8")


def _bridge_method():
    tree = ast.parse(provider_text, filename=str(PROVIDER))
    method = None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "GuangYaProviderReliabilityV1100Mixin":
            continue
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == "_parse_provider_defs":
                method = child
                break
    assert method is not None
    method.returns = None
    for arg in method.args.args:
        arg.annotation = None
    cls = ast.ClassDef(
        name="Bridge",
        bases=[],
        keywords=[],
        body=[method],
        decorator_list=[],
    )
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {}
    exec(compile(module, str(PROVIDER), "exec"), ns)
    return ns["Bridge"]


def test_v1103_restores_missing_provider_parser_name():
    Bridge = _bridge_method()

    class Fake(Bridge):
        def _provider_api_defs(self):
            return [
                {"name": "TG", "kind": "tgsearch", "url": "https://example.invalid/api", "token": "secret"},
                "legacy-noise",
            ]

    rows = Fake()._parse_provider_defs()
    assert rows == [{"name": "TG", "kind": "tgsearch", "url": "https://example.invalid/api", "token": "secret"}]


def test_all_v1100_provider_consumers_resolve_through_bridge():
    assert provider_text.count("self._parse_provider_defs()") >= 2
    assert "provider_defs = list(self._parse_provider_defs())" in console_text
    assert 'getattr(self, "_provider_api_defs", None)' in provider_text


def test_provider_parser_bridge_does_not_touch_transfer_or_download_paths():
    method = provider_text.split("    def _parse_provider_defs", 1)[1].split("    @staticmethod", 1)[0].lower()
    for forbidden in ("create_task", "download", "transfer", "flash", "cloudcollection"):
        assert forbidden not in method
