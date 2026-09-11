from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"

# r97 管理性重构基线。目标是只减不增；确需突破时必须在同一 PR 解释并更新架构文档。
MAX_RUNTIME_PY_FILES = 91
MAX_LEGACY_LINES = 4578
MAX_TOP_LEVEL_MRO_BASES = 47

# 仅允许 ARCHITECTURE.md 6.1 明确记录职责与退出条件的历史特殊层。
# 这个 allowlist 只能减少；新增项必须同步架构文档与 PR 说明。
ALLOWED_LAYERED_MODULES = {
    "dispatch_policy_final_v1125.py",
    "runtime_fix_v1113.py",
}


def _text(path: str) -> str:
    return (PLUGIN / path).read_text(encoding="utf-8")


def test_required_onboarding_docs_exist():
    for name in ("README.md", "ARCHITECTURE.md", "DEVELOPMENT.md", "CHANGELOG.md"):
        assert (PLUGIN / name).is_file(), name
    root_contributing = ROOT / "CONTRIBUTING.md"
    pr_template = ROOT / ".github" / "pull_request_template.md"
    codeowners = ROOT / ".github" / "CODEOWNERS"
    bug_template = ROOT / ".github" / "ISSUE_TEMPLATE" / "guangya_transfer_bug.yml"
    local_validator = ROOT / "scripts" / "validate_guangya.py"
    assert root_contributing.is_file()
    assert pr_template.is_file()
    assert codeowners.is_file()
    assert bug_template.is_file()
    assert local_validator.is_file()


def test_readme_is_entrypoint_not_release_log_wall():
    readme = _text("README.md")
    assert len(readme.splitlines()) < 260
    for token in ("ARCHITECTURE.md", "DEVELOPMENT.md", "CHANGELOG.md", "Fork"):
        assert token in readme
    # 详细版本流水只保留在 CHANGELOG。
    assert readme.count("## v1.") == 0


def test_runtime_module_count_can_only_shrink_without_explicit_policy_change():
    runtime = sorted(PLUGIN.glob("*.py"))
    assert len(runtime) <= MAX_RUNTIME_PY_FILES, (
        f"runtime module count grew to {len(runtime)} > {MAX_RUNTIME_PY_FILES}; "
        "prefer consolidating into an existing Authority"
    )


def test_legacy_file_cannot_keep_growing():
    lines = _text("legacy.py").splitlines()
    assert len(lines) <= MAX_LEGACY_LINES, (
        f"legacy.py grew to {len(lines)} lines; new business logic belongs in a domain Authority"
    )


def test_no_new_versioned_final_impl_fix_hotfix_shells():
    suspicious = {
        path.name
        for path in PLUGIN.glob("*.py")
        if re.search(r"(?:_final_|_impl_|_fix_|_hotfix_|_patch_)v?\d", path.name, re.I)
    }
    assert suspicious <= ALLOWED_LAYERED_MODULES, (
        "new layered compatibility module detected: "
        + ", ".join(sorted(suspicious - ALLOWED_LAYERED_MODULES))
        + "; merge into an existing Authority or document an explicit removal plan"
    )


def test_top_level_mro_can_only_shrink_without_explicit_architecture_change():
    entry = _text("__init__.py")
    block = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    bases = [row.strip() for row in block.split(",") if row.strip()]
    assert len(bases) <= MAX_TOP_LEVEL_MRO_BASES, (
        f"top-level MRO grew to {len(bases)} > {MAX_TOP_LEVEL_MRO_BASES}; "
        "new behavior should enter an existing Authority"
    )


def test_architecture_declares_authority_first_and_no_new_patch_file_policy():
    architecture = _text("ARCHITECTURE.md")
    for token in (
        "Authority",
        "新功能不得通过再加一个顶层 Mixin",
        "*_final_vXXXX.py",
        "legacy.py",
        "Final Plugin E2E",
    ):
        assert token in architecture



def _runtime_import_graph():
    modules = {
        path.stem: path
        for path in PLUGIN.glob("*.py")
    }
    graph = {stem: set() for stem in modules}
    for stem, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 1:
                continue
            # from .foo import Bar
            if node.module:
                target = node.module.split(".", 1)[0]
                if target in modules:
                    graph[stem].add(target)
                continue
            # from . import legacy
            for alias in node.names:
                target = str(alias.name or "").split(".", 1)[0]
                if target in modules:
                    graph[stem].add(target)
    return modules, graph


def test_every_runtime_module_is_reachable_from_final_plugin_entry():
    """没有运行时 import 路径的 .py 会误导 Fork 开发者，应删除或显式接入 Authority。"""
    modules, graph = _runtime_import_graph()
    reachable = {"__init__"}
    queue = ["__init__"]
    while queue:
        current = queue.pop(0)
        for target in graph.get(current, set()):
            if target not in reachable:
                reachable.add(target)
                queue.append(target)

    unreachable = sorted(set(modules) - reachable)
    assert not unreachable, (
        "runtime-unreachable modules: "
        + ", ".join(f"{name}.py" for name in unreachable)
        + "; delete dead code or connect it through an explicit Authority import"
    )



def test_final_entry_docstring_is_runtime_contract_not_version_history():
    entry = _text("__init__.py")
    tree = ast.parse(entry)
    doc = ast.get_docstring(tree, clean=False) or ""
    assert len(doc.splitlines()) < 40
    assert doc.count("v1.") == 0
    for token in (
        "观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
        "managed subscription 不回落 MoviePilot 原生下载",
        "Magnet/ED2K 继续使用光鸭原生 cloudcollection",
        "ARCHITECTURE.md",
        "CHANGELOG.md",
    ):
        assert token in doc



def test_local_validator_covers_root_units_contracts_and_version_consistency():
    validator = (ROOT / "scripts" / "validate_guangya.py").read_text(encoding="utf-8")
    assert '"test_guangya*.py"' in validator
    assert "run_contract_tests.py" in validator
    assert "package.v3.json" in validator
    assert "plugin.json" in validator
    assert "plugin_version" in validator
    assert "--full" in validator



def test_layered_module_allowlist_has_documented_exit_criteria():
    architecture = _text("ARCHITECTURE.md")
    assert "## 6.1 当前仅保留的两个历史特殊层" in architecture
    for filename in sorted(ALLOWED_LAYERED_MODULES):
        assert f"`{filename}`" in architecture
    assert "退出条件" in architecture
    assert "allowlist 只能减少" in architecture
