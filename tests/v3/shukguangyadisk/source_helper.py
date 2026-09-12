"""ShukGuangYaDisk single-init test source adapter.

Historical contracts still validate the exact module source that is bundled inside
plugins.v3/shukguangyadisk/__init__.py, without requiring those modules to exist
as physical .py files.
"""
from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = ROOT / "plugins.v3" / "shukguangyadisk"
REAL_ENTRY = PLUGIN_DIR / "__init__.py"

_cache: tuple[Dict[str, str], str, str] | None = None


def _read_bundle() -> tuple[Dict[str, str], str, str]:
    global _cache
    if _cache is not None:
        return _cache

    physical = REAL_ENTRY.read_text(encoding="utf-8")
    tree = ast.parse(physical, filename=str(REAL_ENTRY))
    bundled_json = None
    entry_source = None

    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_BUNDLED_SOURCES":
                value = node.value
                if not isinstance(value, ast.Call) or not value.args:
                    raise AssertionError("_BUNDLED_SOURCES must be loaded from a literal JSON payload")
                raw = value.args[0]
                if not isinstance(raw, ast.Constant) or not isinstance(raw.value, str):
                    raise AssertionError("_BUNDLED_SOURCES JSON payload must be a literal string")
                bundled_json = raw.value
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "_ENTRY_SOURCE" in names:
                if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                    raise AssertionError("_ENTRY_SOURCE must be a literal string")
                entry_source = node.value.value

    if bundled_json is None or entry_source is None:
        raise AssertionError("single-init bundle markers are missing")

    sources = json.loads(bundled_json)
    if not isinstance(sources, dict):
        raise AssertionError("single-init source bundle must be a dict")
    _cache = (sources, entry_source, physical)
    return _cache


def bundled_sources() -> Dict[str, str]:
    return dict(_read_bundle()[0])


def physical_init_text() -> str:
    return _read_bundle()[2]


def source_text(filename: str) -> str:
    if filename == "__init__.py":
        return _read_bundle()[1]
    key = filename[:-3] if filename.endswith(".py") else filename
    try:
        return _read_bundle()[0][key]
    except KeyError as err:
        raise FileNotFoundError(filename) from err


class EmbeddedSourcePath:
    def __init__(self, filename: str):
        self.filename = filename

    @property
    def name(self) -> str:
        return self.filename

    def read_text(self, encoding: str = "utf-8") -> str:
        del encoding
        return source_text(self.filename)

    def exists(self) -> bool:
        try:
            source_text(self.filename)
        except FileNotFoundError:
            return False
        return True

    def __str__(self) -> str:
        return f"{REAL_ENTRY}::<embedded:{self.filename}>"


class SingleInitPluginPath:
    def __init__(self, root: Path):
        self.root = Path(root)

    def __truediv__(self, child):
        name = str(child)
        if name.endswith(".py"):
            return EmbeddedSourcePath(name)
        return self.root / child

    def __str__(self) -> str:
        return str(self.root)


def single_init_plugin_path(root: Path) -> SingleInitPluginPath:
    return SingleInitPluginPath(root)


def load_embedded_module(filename: str, module_name: str):
    source = source_text(filename)
    module = types.ModuleType(module_name)
    module.__file__ = f"{REAL_ENTRY}::<embedded:{filename}>"
    module.__package__ = ""
    sys.modules[module_name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__, module.__dict__)
    return module
