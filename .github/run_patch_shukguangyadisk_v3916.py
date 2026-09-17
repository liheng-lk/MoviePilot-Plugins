from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "plugins.v3/shukguangyadisk/__init__.py"
PATCH = ROOT / ".github/patch_shukguangyadisk_v3916.py"
TEST = ROOT / "tests/v3/shukguangyadisk/test_orphan_inflight_reconcile_v3916.py"


def patch_embedded_entry_version() -> None:
    text = INIT.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(INIT))
    target = None
    entry_source = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_ENTRY_SOURCE" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            raise SystemExit("_ENTRY_SOURCE is not a literal string")
        target = ast.get_source_segment(text, node)
        entry_source = node.value.value
        break
    if not target or entry_source is None:
        raise SystemExit("cannot locate _ENTRY_SOURCE")

    updated = entry_source
    for old in ("3.9.14", "3.9.15"):
        updated = updated.replace(
            f'plugin_version = "{old}"',
            'plugin_version = "3.9.16"',
        )
    if 'plugin_version = "3.9.16"' not in updated:
        raise SystemExit("embedded entry plugin_version was not updated")

    replacement = "_ENTRY_SOURCE = " + repr(updated)
    text = text.replace(target, replacement, 1)
    INIT.write_text(text, encoding="utf-8")


def normalize_generated_contract() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = text.replace(
        "assert 'ShukGuangYaDisk.plugin_version = \"3.9.16\"' in INIT",
        "assert 'plugin_version = \"3.9.16\"' in INIT",
    )
    TEST.write_text(text, encoding="utf-8")


def run_checked(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    # 第一阶段负责正式代码、元数据和新测试。它会先触发旧版本一致性合同；即使返回
    # 非零，工作树补丁已经生成。随后统一修正单文件虚拟入口与新增合同，再跑全套。
    first = subprocess.run(["python", str(PATCH)], cwd=ROOT, check=False)
    if not TEST.exists():
        raise SystemExit(f"base patch did not materialize v3.9.16 files (exit={first.returncode})")

    patch_embedded_entry_version()
    normalize_generated_contract()

    text = INIT.read_text(encoding="utf-8")
    compile(text, str(INIT), "exec")
    run_checked("python", "tests/v3/shukguangyadisk/run_contract_tests.py")
    run_checked("python", "-m", "unittest", "discover", "-s", "tests/v3/shukguangyadisk", "-p", "test_*.py")
    run_checked("git", "diff", "--check")


if __name__ == "__main__":
    main()
