from __future__ import annotations

from source_helper import single_init_plugin_path
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
PATCH = (PLUGIN / "organizer_legacy_queue_cleanup_v343.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_v3100_legacy_queue_cleanup_is_strict_readonly_observer():
    assert "destructive_cleanup_disabled" in PATCH
    assert "observed_waiting" in PATCH
    assert "observed_running" in PATCH
    for forbidden in (
        "pending_oper.discard(",
        "remove_from_queue(",
        "global_vars.stop_transfer(",
        "TransferPendingOper()",
    ):
        assert forbidden not in PATCH, forbidden


def test_v3100_legacy_cleanup_no_longer_patches_monitor_init():
    install = PATCH[PATCH.index("def install_legacy_queue_cleanup_v343"):]
    assert "init_organizer_monitor =" not in install
    assert "_guangya_legacy_cleanup_v343 = True" in install


def test_v3100_candidate_filter_does_not_install_legacy_queue_migrator():
    assert "from .organizer_legacy_queue_cleanup_v343 import install_legacy_queue_cleanup_v343" not in FILTER
    assert "install_legacy_queue_cleanup_v343()" not in FILTER


def test_v3100_observer_still_scopes_snapshot_to_guangya_storage_and_monitor_path():
    assert "storage not in storage_names" in PATCH
    assert "not self._queue_guard_path_matches(path)" in PATCH
