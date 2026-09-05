from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v372_release_tree_has_no_one_time_tooling():
    for rel in (
        "tools/migrate_shuk_v372_phase2.py",
        "tools/update_shuk_v372_contracts.py",
        "tools/fix_shuk_v372_contract_scope.py",
        "tools/stage_shuk_v372_release.py",
        "tools/fix_shuk_v372_release_contracts.py",
        ".github/workflows/migrate-shuk-v372-phase2.yml",
        ".github/workflows/stage-shuk-v372-release.yml",
    ):
        assert not (ROOT / rel).exists(), rel
