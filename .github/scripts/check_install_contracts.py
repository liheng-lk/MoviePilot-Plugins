#!/usr/bin/env python3
"""校验 MoviePilot 插件仓库的可安装合同。

在官方版本门禁和 Federation CSS 门禁之外，补充第三方仓库长期维护需要的安装一致性：
- package 索引必须有对应目录和真实物理主类；
- 主类 plugin_version、索引 version、可选 plugin.json version 必须一致；
- history 首项必须等于当前版本并按语义版本降序；
- V3 专用实现必须声明 >=3.0.0；
- V2 与 V3 同名时，旧代条目必须 v3=false，避免 V3 回退旧实现；
- Federation 插件必须 release=true；
- release=true 的 Tag/ZIP 命名合同可由发布工作流直接推导。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIRS = {
    "package.v2.json": ROOT / "plugins.v2",
    "package.v3.json": ROOT / "plugins.v3",
}
SEMVER_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _semver(value: object) -> tuple[int, ...] | None:
    match = SEMVER_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _cmp(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right), 3)
    a = left + (0,) * (width - len(left))
    b = right + (0,) * (width - len(right))
    return (a > b) - (a < b)


def _physical_class_version(init_file: Path, plugin_id: str) -> str | None:
    try:
        tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != plugin_id:
            continue
        for stmt in node.body:
            value = None
            if isinstance(stmt, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in stmt.targets):
                    value = stmt.value
            elif (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == "plugin_version"
            ):
                value = stmt.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def _history_errors(package_name: str, plugin_id: str, meta: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    version = str(meta.get("version") or "").strip()
    parsed_version = _semver(version)
    history = meta.get("history")
    if not isinstance(history, dict) or not history:
        return [f"{package_name}: {plugin_id} 缺少非空 history"]
    keys = list(history)
    parsed = [_semver(item) for item in keys]
    if parsed_version is None:
        errors.append(f"{package_name}: {plugin_id} 当前版本 {version!r} 非法")
    if parsed and parsed[0] is not None and parsed_version is not None and _cmp(parsed[0], parsed_version) != 0:
        errors.append(f"{package_name}: {plugin_id} history 首项 {keys[0]} 与当前版本 {version} 不一致")
    for key, item in zip(keys, parsed):
        if item is None:
            errors.append(f"{package_name}: {plugin_id} history 包含非法版本 {key}")
    for left_key, left, right_key, right in zip(keys, parsed, keys[1:], parsed[1:]):
        if left is not None and right is not None and _cmp(left, right) < 0:
            errors.append(
                f"{package_name}: {plugin_id} history 未按语义版本降序：{left_key} 在 {right_key} 之前"
            )
    return errors


def _is_federation_plugin(plugin_dir: Path) -> bool:
    if any(path.is_file() for path in plugin_dir.glob("**/remoteEntry.js")):
        return True
    for config in plugin_dir.glob("vite.config.*"):
        if config.is_file() and re.search(r"\bfederation\s*\(", config.read_text(encoding="utf-8")):
            return True
    return False


def check() -> list[str]:
    errors: list[str] = []
    packages = {
        name: _load_json(ROOT / name)
        for name in PACKAGE_DIRS
    }
    v3_package = packages.get("package.v3.json", {})

    for package_name, base_dir in PACKAGE_DIRS.items():
        package = packages.get(package_name, {})
        for plugin_id, raw_meta in package.items():
            if not isinstance(raw_meta, dict):
                errors.append(f"{package_name}: {plugin_id} 元数据必须是对象")
                continue
            meta: dict[str, Any] = raw_meta
            plugin_dir = base_dir / plugin_id.lower()
            init_file = plugin_dir / "__init__.py"
            if not plugin_dir.is_dir():
                errors.append(f"{package_name}: {plugin_id} 缺少目录 {plugin_dir.relative_to(ROOT)}")
                continue
            if not init_file.is_file():
                errors.append(f"{package_name}: {plugin_id} 缺少 {init_file.relative_to(ROOT)}")
                continue

            class_version = _physical_class_version(init_file, plugin_id)
            package_version = str(meta.get("version") or "").strip()
            if class_version is None:
                errors.append(
                    f"{package_name}: {plugin_id} 必须在 __init__.py 物理定义同名主类并声明 plugin_version"
                )
            elif class_version != package_version:
                errors.append(
                    f"{package_name}: {plugin_id} 版本不一致：package={package_version}, class={class_version}"
                )

            plugin_json = plugin_dir / "plugin.json"
            if plugin_json.is_file():
                try:
                    plugin_json_version = str(_load_json(plugin_json).get("version") or "").strip()
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"{plugin_json.relative_to(ROOT)}: JSON 无法读取：{exc}")
                else:
                    if plugin_json_version and plugin_json_version != package_version:
                        errors.append(
                            f"{plugin_json.relative_to(ROOT)}: version={plugin_json_version} "
                            f"与 {package_name}={package_version} 不一致"
                        )

            errors.extend(_history_errors(package_name, plugin_id, meta))

            if package_name == "package.v3.json":
                system_version = str(meta.get("system_version") or "").replace(" ", "")
                if ">=3.0.0" not in system_version:
                    errors.append(
                        f"{package_name}: {plugin_id} V3 专用实现必须声明 system_version >=3.0.0"
                    )

            if _is_federation_plugin(plugin_dir) and meta.get("release") is not True:
                errors.append(f"{package_name}: Federation 插件 {plugin_id} 必须 release=true")

            if meta.get("release") is True:
                expected_tag = f"{plugin_id}_v{package_version}"
                expected_asset = f"{plugin_id.lower()}_v{package_version}.zip"
                if not _semver(package_version):
                    errors.append(
                        f"{package_name}: {plugin_id} Release 版本非法，无法生成 {expected_tag}/{expected_asset}"
                    )

    # 官方文档要求：已有 V3 专用副本时，旧代同名条目必须 v3=false，避免回退旧实现。
    v2_package = packages.get("package.v2.json", {})
    for plugin_id, v2_meta in v2_package.items():
        if plugin_id in v3_package and isinstance(v2_meta, dict) and v2_meta.get("v3") is not False:
            errors.append(
                f"package.v2.json: {plugin_id} 已有 V3 专用实现，旧代条目必须设置 v3=false"
            )

    return errors


def main() -> int:
    errors = check()
    if errors:
        print("插件安装合同门禁失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("插件安装合同门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
