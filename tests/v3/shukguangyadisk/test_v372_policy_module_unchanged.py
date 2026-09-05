from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = (ROOT / "plugins.v3/shukguangyadisk/organizer_policy.py").read_text(encoding="utf-8")


def test_v372_canonical_dispositions_remain_in_one_policy_module():
    for token in ("LEAVE_UNRECOGNIZED", "DELETE_DUPLICATE", "ORGANIZE_VERSION", "RETRY_TRANSIENT", "BLOCK_SAFETY", "RETIRE_MISSING"):
        assert token in POLICY
