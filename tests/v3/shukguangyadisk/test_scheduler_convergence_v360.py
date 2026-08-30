from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_scheduler_convergence_v360.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")


def test_empty_path_is_not_normalized_to_root_anymore():
    assert 'raw = str(value or "").strip()' in PATCH
    assert 'if not raw:\n        return ""' in PATCH
    assert 'sticky == "/"' in PATCH
    assert 'v3.6.0 清理无效/根目录 sticky' in PATCH


def test_corrupt_root_sticky_is_cleared_instead_of_scanned():
    assert '_clear_corrupt_sticky(plugin, "v3.6.0 清理无效/根目录 sticky")' in PATCH
    assert 'return ""' in PATCH
    assert 'sticky_tv_group_path=""' in PATCH


def test_worker_handoff_freezes_old_discovery_and_refill_timer():
    for token in (
        'setattr(owner, _FREEZE_ATTR, True)',
        'setattr(owner, "_organize_monitor_enabled", False)',
        'timer.cancel()',
        'owner._process_folder_group = types.MethodType(frozen_process, owner)',
        'owner.run_organize_monitor_scan = types.MethodType(frozen_scan, owner)',
    ):
        assert token in PATCH, token


def test_false_worker_retries_are_removed_not_backed_off_again():
    for marker in (
        '私有 worker 当前未接收文件夹任务',
        'MoviePilot 预检允许提交，但当前未接收入队',
    ):
        assert marker in PATCH
    assert 'retry.pop(path, None)' in PATCH
    assert '真实失败 retry 未修改' in PATCH


def test_init_is_idempotent_at_outer_queue_recovery_boundary():
    assert 'previous_init = GuangYaQueueRecoveryMixin.init_organizer_monitor' in PATCH
    assert 'if bool(getattr(self, "_organize_monitor_initialized", False)) and not force:' in PATCH
    assert 'return previous_init(self, force=force)' in PATCH


def test_v360_is_the_only_current_paged_discovery_install():
    assert 'install_scheduler_convergence_v360(GuangYaCandidateFilterMixin)' in FILTER
    assert 'install_paged_scan_handoff_v359(GuangYaCandidateFilterMixin)' not in FILTER
    assert 'candidate_mixin._iter_folder_groups = _iter_groups' in PATCH


def test_v360_keeps_real_50_directory_persistent_cursor():
    for token in (
        '_PAGE_DIR_LIMIT = 50',
        '_CURSOR_KEY = "organize_v360_scan_cursor"',
        'while queue and dirs_scanned < _PAGE_DIR_LIMIT:',
        '"queue": list(queue)',
        '"inventory_paths": list(inventory)',
        '下次从游标继续',
    ):
        assert token in PATCH, token


def test_stability_wait_no_longer_fast_refills_the_whole_library():
    assert '稳定性等待不再触发 3 秒翻页扫完整库' in FILTER
    assert 'stability_wait=' not in FILTER
    assert 'no_capacity_backlog' in FILTER


def test_scheduler_does_not_take_over_moviepilot_business_rules():
    for forbidden in (
        'target_directory',
        'rename_format',
        'get_rename_path',
        'category.yaml',
    ):
        assert forbidden not in PATCH
