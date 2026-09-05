from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "tests/v3/shukguangyadisk"


def test_v372_canonical_contract_files_exist():
    for name in (
        "test_organizer_phase2_v372_contract.py",
        "test_release_v372.py",
        "test_phase2_doc_v372.py",
        "test_phase2_no_temp_tooling_v372.py",
    ):
        assert (BASE / name).exists(), name
