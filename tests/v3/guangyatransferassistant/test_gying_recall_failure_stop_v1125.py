from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GUARD = (PLUGIN / "gying_recall_guard_v1125.py").read_text(encoding="utf-8")


def _method(name: str, next_name: str | None = None) -> str:
    start = GUARD.index(f"    def {name}(")
    if next_name:
        return GUARD[start:GUARD.index(f"    def {next_name}(", start)]
    return GUARD[start:]


def test_search_failure_marks_retry_round_as_terminal():
    ast.parse(GUARD)
    search = _method("_search_viewing_xunlei", "_merge_xunlei_rounds_v1125")
    failure = search.split('if not last_state.get("success"):', 1)[1].split("successful.append(variant)", 1)[0]
    assert "retry_local.stop_after_failure = True" in failure


def test_dispatch_never_widens_after_node_login_or_http_search_failure():
    dispatch = _method("_dispatch_xunlei_flash", "_viewing_external_candidates_v1113")
    lower = dispatch.index("super()._dispatch_xunlei_flash(subscribe)")
    stop = dispatch.index('getattr(local, "stop_after_failure", False)', lower)
    next_index = dispatch.index("next_index = last_index + 1", stop)
    assert lower < stop < next_index
    assert 'tracked = ("start_index", "last_attempted_index", "seen_identities", "stop_after_failure")' in dispatch
    assert "local.stop_after_failure = False" in dispatch
