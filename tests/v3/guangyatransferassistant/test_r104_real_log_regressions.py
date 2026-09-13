"""r104 real-environment regressions: GYING live session, sequel identity, planner diagnostics."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _bundles() -> dict[str, str]:
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return {str(k): str(v) for k, v in value.items()}
    raise AssertionError("_BUNDLED_SOURCES missing")


def _bundle(name: str) -> str:
    return _bundles()[name]


def _bundle_with(marker: str) -> str:
    matches = [source for source in _bundles().values() if marker in source]
    assert len(matches) == 1, f"expected one bundle for {marker!r}, got {len(matches)}"
    return matches[0]


def _exec_identity():
    ns = {}
    exec(compile(_bundle("media_identity_v1111"), "<media_identity_v1111>", "exec"), ns)
    return ns


def test_numbered_sequel_can_bridge_publisher_base_title_plus_real_season():
    ns = _exec_identity()
    helper = ns["sequel_numbered_title_season_alias_v1111"]
    assess = ns["assess_media_identity_v1111"]

    assert helper(
        ["我们的少年时代2"],
        1,
        {2},
        ["我们的少年时代 (2026) S02", "我们的少年时代.S02E15.mkv"],
        expected_year=2026,
    )
    # Ordinary series titles without the explicit sequel number stay blocked.
    assert not helper(
        ["我们的少年时代"],
        1,
        {2},
        ["我们的少年时代 (2026) S02", "我们的少年时代.S02E15.mkv"],
        expected_year=2026,
    )

    allowed = assess(
        aliases=["我们的少年时代2"],
        expected_year=2026,
        expected_season=1,
        is_movie=False,
        primary_evidences=["我们的少年时代 (2026) S02"],
        file_evidences=["我们的少年时代.S02E15.mkv"],
        threshold=100,
    )
    assert allowed["ok"] is True
    assert allowed["hard_conflict"] is False
    assert allowed["score"] == 100

    blocked = assess(
        aliases=["我们的少年时代"],
        expected_year=2026,
        expected_season=1,
        is_movie=False,
        primary_evidences=["我们的少年时代 (2026) S02"],
        file_evidences=["我们的少年时代.S02E15.mkv"],
        threshold=50,
    )
    assert blocked["ok"] is False
    assert blocked["hard_conflict"] is True
    assert blocked["reason_code"] == "SEASON_MISMATCH"


def test_gying_r104_uses_one_live_in_memory_session_and_transaction_lock():
    assert 'build_id = "20260913-r104"' in ENTRY
    assert "_gying_transaction_lock_r104 = threading.RLock()" in ENTRY
    assert 'def _gying_new_session(self, node: str, saved_cookie: str = "")' in ENTRY
    assert "self._gying_live_sessions_r104" in ENTRY
    assert "PanSou PoW：复用当前活 Session" in ENTRY
    assert "def _gying_raw_results(self, keyword: str, force: bool = False)" in ENTRY
    assert "with self._gying_transaction_lock_r104:" in ENTRY
    assert "观影机器人验证完成后原请求仍返回挑战页" in ENTRY
    assert "self._gying_drop_live_session_r104(node, expected_session=session)" in ENTRY


def test_xunlei_ambiguous_planner_keeps_hard_gate_but_logs_file_diagnostics():
    source = _bundle_with("【光鸭转存助手】【拆包v1.12.7】")
    assert 'result.get("diagnostics")' in source
    assert "diagnostics[:8]" in source
    assert "message=%s diag=%s" in source
    # Observability only: no downgrade of the 0.90 automatic-selection threshold.
    resolver = _bundle("episode_resolver_v190")
    assert "AUTO_SELECT_CONFIDENCE = 0.90" in resolver
