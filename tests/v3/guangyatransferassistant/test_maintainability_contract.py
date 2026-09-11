from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"

# r97 管理性重构基线。目标是只减不增；确需突破时必须在同一 PR 解释并更新架构文档。
MAX_RUNTIME_PY_FILES = 93
MAX_LEGACY_LINES = 4578
MAX_TOP_LEVEL_MRO_BASES = 48

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
    assert root_contributing.is_file()
    assert pr_template.is_file()


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
