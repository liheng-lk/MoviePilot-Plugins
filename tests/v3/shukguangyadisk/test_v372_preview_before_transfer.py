from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFLICT = (ROOT / "plugins.v3/shukguangyadisk/organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")


def test_v372_preview_remains_before_real_folder_transfer():
    block = CONFLICT[CONFLICT.index("def _execute_conflict_aware"):]
    assert block.index('preview_kwargs["preview"] = True') < block.index("_loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))")
