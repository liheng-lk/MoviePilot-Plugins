from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEST = ROOT / "tests/v3/shukguangyadisk"


def test_v371_phase2_release_contract_files_exist():
    for name in (
        "test_organizer_phase2_v371_contract.py",
        "test_release_v371.py",
        "test_phase2_no_temp_tooling_v371.py",
    ):
        assert (TEST / name).exists(), name
