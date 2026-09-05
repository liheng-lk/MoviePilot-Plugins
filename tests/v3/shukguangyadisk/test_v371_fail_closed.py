from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "plugins.v3/shukguangyadisk/organizer_policy.py"


def _load_policy():
    spec = importlib.util.spec_from_file_location("shuk_v371_policy_fail_closed", POLICY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v371_unknown_size_still_blocks_destructive_action():
    policy = _load_policy()
    assert policy.decide_existing_target(None, 2000) == policy.FileDisposition.BLOCK_SAFETY
    assert policy.decide_existing_target(1000, None) == policy.FileDisposition.BLOCK_SAFETY
    assert policy.decide_existing_target("", 2000) == policy.FileDisposition.BLOCK_SAFETY


def test_v371_known_equal_and_different_sizes_keep_v370_semantics():
    policy = _load_policy()
    assert policy.decide_existing_target(1000, 1000) == policy.FileDisposition.DELETE_DUPLICATE
    assert policy.decide_existing_target(1000, 2000) == policy.FileDisposition.ORGANIZE_VERSION
