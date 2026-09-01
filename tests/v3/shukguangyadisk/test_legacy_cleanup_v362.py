from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CLEANUP = (PLUGIN / "organizer_legacy_queue_cleanup_v343.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v362_legacy_cleanup_is_no_longer_every_init_hot_path():
    assert "_V362_RECHECK_SECONDS = 60.0" in CLEANUP
    assert 'checked = bool(getattr(self, "_v362_legacy_cleanup_checked", False))' in CLEANUP
    assert "if checked and now_mono < next_recheck:" in CLEANUP
    assert "本实例永久退出迁移热路径" in CLEANUP
    assert "每次初始化都会重新检查" not in CLEANUP


def test_v362_never_touches_moviepilot_queue_while_private_worker_is_alive():
    assert "def _isolated_runtime_active" in CLEANUP
    for token in (
        'snapshot.get("running_path")',
        'snapshot.get("queued")',
        'snapshot.get("owned")',
        'snapshot.get("worker_alive")',
        'snapshot.get("owner_worker_alive")',
    ):
        assert token in CLEANUP, token
    cleanup_start = CLEANUP.index("def _cleanup_legacy_global_tasks")
    transfer_chain_pos = CLEANUP.index("chain = TransferChain()", cleanup_start)
    guard_pos = CLEANUP.index("if _isolated_runtime_active(self):", cleanup_start)
    assert guard_pos < transfer_chain_pos
    assert 'skipped="isolated_worker_active"' in CLEANUP


def test_v362_retained_running_is_low_frequency_and_existing_source_is_not_force_deleted():
    assert "_V362_RETAINED_LOG_SECONDS = 300.0" in CLEANUP
    assert "源文件仍存在" in CLEANUP
    assert "每 60 秒安全复查一次" in CLEANUP
    assert "不会强制删除仍存在的源文件" in CLEANUP
    assert "仅低频复查" in CLEANUP


def test_v362_cleanup_still_scopes_to_guangya_monitored_paths_only():
    assert "storage not in storage_names" in CLEANUP
    assert "not self._queue_guard_path_matches(path)" in CLEANUP
    assert "其它存储未处理" in CLEANUP


def test_v362_release_metadata_is_preserved_by_later_patch_versions():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    current = plugin_meta["version"]
    assert current == package_meta["ShukGuangYaDisk"]["version"]
    assert f'plugin_version = "{current}"' in ENTRY
    assert f'?v={current}' in REMOTE
    assert "v3.6.2" in plugin_meta["history"]


def test_v362_does_not_change_moviepilot_business_rules():
    for forbidden in (
        "target_directory",
        "rename_format",
        "get_rename_path",
        "category.yaml",
        "tmdbid=",
    ):
        assert forbidden not in CLEANUP, forbidden
