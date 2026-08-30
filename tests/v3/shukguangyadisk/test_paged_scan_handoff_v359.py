from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_paged_scan_handoff_v359.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v359_uses_persistent_50_directory_cursor():
    for token in (
        '_CURSOR_KEY = "organize_v359_paged_scan_cursor"',
        '_PAGE_DIR_LIMIT = 50',
        'while queue and dirs_scanned < _PAGE_DIR_LIMIT:',
        '"queue": list(queue)',
        '"seen_dirs": list(seen_dirs)',
        '"inventory_paths": list(inventory)',
        '下一轮从断点继续',
    ):
        assert token in PATCH, token


def test_v359_partial_pages_never_prune_unseen_state():
    assert 'scan_meta["truncated"] = True' in PATCH
    assert 'scan_meta["inventory_paths"] = set(inventory)' in PATCH
    assert 'scan_meta["truncated"] = False' in PATCH
    assert '完整走完本 cycle' in PATCH


def test_v359_preserves_single_flight_and_streaming_container_progress():
    for token in (
        'setattr(plugin, "_guangya_single_flight_claimed_v350", False)',
        '_worker_busy(snapshot)',
        'if getattr(plugin, "_guangya_single_flight_claimed_v350", False):',
        'queue.insert(0, current_path)',
        'scan_meta["single_flight_partial"] = True',
    ):
        assert token in PATCH, token


def test_v359_sticky_group_is_prioritized_before_cursor():
    sticky_pos = PATCH.index('sticky = _sticky_group(plugin)')
    cursor_pos = PATCH.index('cursor = _load_cursor(plugin, root)')
    assert sticky_pos < cursor_pos
    assert 'yield from _yield_sticky_first(plugin, sticky, scan_meta)' in PATCH
    assert 'paged_sticky_priority' in PATCH


def test_v359_worker_handoff_pauses_scan_and_then_immediately_resumes():
    for token in (
        'snapshot.get("owner_worker_alive")',
        'not snapshot.get("owner_current")',
        'claimed = bool(self._claim_isolated_runtime())',
        'return self.run_organize_monitor_scan(manual=False)',
        'Worker 交接中，等待继续当前资源',
        'Worker交接】已取得新 worker 所有权',
    ):
        assert token in PATCH, token


def test_v359_projects_sticky_path_as_current_resource_during_handoff():
    assert 'status["current_task_path"] = sticky' in PATCH
    assert 'Worker 交接中，等待继续当前剧集' in PATCH
    assert 'status["scan_page_size"] = _PAGE_DIR_LIMIT' in PATCH


def test_v359_installs_after_v358_as_final_discovery_layer():
    assert 'from .organizer_paged_scan_handoff_v359 import install_paged_scan_handoff_v359' in FILTER
    assert FILTER.index('install_paged_scan_handoff_v359(GuangYaCandidateFilterMixin)') > FILTER.index('install_season_context_v358()')
    assert '50 目录游标分页，sticky 优先，worker 交接期间不扫库' in FILTER


def test_v359_release_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "3.5.9"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.5.9"
    assert 'plugin_version = "3.5.9"' in ENTRY
    assert '?v=3.5.9' in REMOTE
    assert 'v3.5.9' in plugin_meta["history"]


def test_v359_keeps_moviepilot_business_rules_untouched():
    for forbidden in (
        'target_directory',
        'rename_format',
        'DirectoryHelper',
        'get_rename_path',
    ):
        assert forbidden not in PATCH
