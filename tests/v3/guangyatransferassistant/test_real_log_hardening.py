"""Real-log development regressions without changing the public 2.1.5-r103 release marker."""
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


def test_gying_hardening_keeps_public_build_r103_and_reuses_live_session():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert 'plugin_version = "2.1.5"' in final
    assert 'build_id = "20260913-r103"' in final
    assert "v2.1.5-r104 实机热修" not in ENTRY[:1200]
    assert "_gying_transaction_lock_r104 = threading.RLock()" in final
    assert 'def _gying_new_session(self, node: str, saved_cookie: str = "")' in final
    assert "self._gying_live_sessions_r104" in final
    assert "PanSou PoW：复用当前活 Session" in final
    assert "self._gying_drop_live_session_r104(node, expected_session=session)" in final


def test_same_run_gying_hard_failure_is_not_retried_by_lower_priority_stage():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert "self._gying_run_failures_dev = {}" in final
    assert "def _gying_run_failure_key_dev" in final
    assert "def _gying_get_run_failure_dev" in final
    assert "def _gying_store_run_failure_dev" in final
    assert 'state["transport"] = "run_failure_memo"' in final
    assert "同轮失败复用" in final
    assert final.count("self._gying_store_run_failure_dev(keyword, state)") >= 2


def test_expired_pending_library_rows_are_released_after_one_aggregated_warning():
    source = _bundle_with("action=expired_pending_released")
    assert "expired_missing: Set[int] = set()" in source
    assert "expired_missing |= remain" in source
    assert "items.pop(key, None)" in source
    assert source.count("action=expired_pending_released") == 1


def test_channel_statistics_use_canonical_slug_instead_of_blind_url_truncation():
    source = _bundle_with("【频道资源统计】channel=%s")
    assert 'raw_channel = str(row.get("channel") or row.get("source_url") or "-").strip()' in source
    assert "self._channel_slug_from_source_v209(raw_channel)" in source
    assert 'str(row.get("channel") or row.get("source_url") or "-")[-40:]' not in source


def test_xunlei_ambiguous_planner_keeps_hard_gate_but_logs_file_diagnostics():
    source = _bundle_with("【光鸭转存助手】【拆包v1.12.7】")
    assert 'result.get("diagnostics")' in source
    assert "diagnostics[:8]" in source
    assert "message=%s diag=%s" in source
    resolver = _bundle("episode_resolver_v190")
    assert "AUTO_SELECT_CONFIDENCE = 0.90" in resolver
