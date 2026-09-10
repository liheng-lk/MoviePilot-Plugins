from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_partial_revisit_v375.py"
CANDIDATE = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_candidate_filter.py"


def test_partial_success_with_waiting_siblings_re_registers_pending():
    source = PATCH.read_text(encoding="utf-8")
    assert 'if not bool(result.get("scheduled")):' in source
    assert "remaining_wait = _remaining_wait_count(result)" in source
    assert 'pending_result["scheduled"] = False' in source
    assert 'pending_result["reason"] = "partial_wait"' in source
    assert "register_pending(group_path, files, pending_result)" in source


def test_only_revisitable_wait_phases_keep_partial_resource_alive():
    source = PATCH.read_text(encoding="utf-8")
    assert '_WAIT_PHASES = ("stabilizing", "history_wait", "retry_wait", "inflight")' in source
    constant_line = next(line for line in source.splitlines() if line.startswith("_WAIT_PHASES = "))
    assert '"completed"' not in constant_line
    assert '"blocked"' not in constant_line
    assert '"ignored"' not in constant_line
    assert '"unknown"' not in constant_line


def test_partial_revisit_patch_is_installed_in_runtime_graph():
    source = CANDIDATE.read_text(encoding="utf-8")
    assert "from .organizer_partial_revisit_v375 import install_partial_revisit_v375" in source
    assert "install_partial_revisit_v375()" in source
