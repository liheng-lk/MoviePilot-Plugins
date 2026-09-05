from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_v371_release_branch_contains_no_one_time_migration_tooling():
    for path in (
        ROOT / ".github/scripts/migrate_shuk_v371_policy_execution.py",
        ROOT / ".github/scripts/update_shuk_v371_contracts.py",
        ROOT / ".github/scripts/stage_shuk_v371_release.py",
        ROOT / ".github/workflows/migrate-shuk-v371-phase2.yml",
        ROOT / ".github/workflows/stage-shuk-v371-release.yml",
    ):
        assert not path.exists(), path
