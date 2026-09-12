"""Test helpers for the single-file GuangYa runtime bundle."""

from __future__ import annotations

import ast
import types
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"


@lru_cache(maxsize=1)
def entry_text() -> str:
    return ENTRY_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def entry_tree() -> ast.Module:
    return ast.parse(entry_text(), filename=str(ENTRY_PATH))


@lru_cache(maxsize=1)
def bundled_sources() -> dict[str, str]:
    for node in entry_tree().body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                raise AssertionError("_BUNDLED_SOURCES must be a dict")
            return {str(key): str(source) for key, source in value.items()}
    raise AssertionError("_BUNDLED_SOURCES assignment not found in GuangYa __init__.py")


def bundle_source(module_name: str) -> str:
    try:
        return bundled_sources()[module_name]
    except KeyError as err:
        raise AssertionError(f"bundled module missing: {module_name}") from err


def entry_class_bases() -> list[str]:
    classes = [
        node for node in entry_tree().body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaTransferAssistant"
    ]
    if len(classes) != 1:
        raise AssertionError(f"expected one top-level GuangYaTransferAssistant, got {len(classes)}")
    names: list[str] = []
    for base in classes[0].bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
        else:
            names.append(ast.unparse(base))
    return names


def exec_bundled_module(module_name: str) -> types.ModuleType:
    source = bundle_source(module_name)
    module = types.ModuleType(f"_guangya_test_{module_name}")
    module.__file__ = f"{ENTRY_PATH}::<{module_name}.py>"
    module.__package__ = ""
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module
