from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "guangya_move_transaction_guard_v364.py").read_text(encoding="utf-8")
EXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
LEGACY = (PLUGIN / "_plugin_legacy.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v364_wraps_final_v360_move_item_before_moviepilot_can_see_failure():
    assert "from .guangya_move_transaction_guard_v364 import install_move_transaction_guard_v364" in EXECUTION
    v360 = EXECUTION.index("install_move_confirmation_v360()")
    v364 = EXECUTION.index("install_move_transaction_guard_v364()")
    ready = EXECUTION.index("self._v360_storage_patch_ready = True")
    assert v360 < v364 < ready
    assert "previous_move_item = GuangYaApi.move_item" in PATCH
    assert "result = previous_move_item(self, fileitem, path, target_name)" in PATCH


def test_v364_late_visible_target_is_rescued_as_success_not_failure_cleanup():
    assert "_EXTENDED_CONFIRM_TRIES = 60" in PATCH
    assert "exact_target = _confirmed_named_item(" in PATCH
    assert "前序返回失败，但 MoviePilot 目标文件随后已真实可见，按成功收口" in PATCH
    assert "return exact_target" in PATCH
    rescue = PATCH[PATCH.index("result = previous_move_item"):PATCH.index("source_actual = _find_named_matching")]
    assert "_protect_failed_move(" not in rescue


def test_v364_rename_only_failure_retries_confirmation_before_rollback():
    target = PATCH.index("target_actual = _target_candidate(")
    retry = PATCH.index("if self.rename(target_actual, target_name):", target)
    rollback = PATCH.index("_rollback_to_source(", retry)
    assert target < retry < rollback
    assert "跨目录 move 已完成，仅 rename 延迟；重试确认后按成功收口" in PATCH


def test_v364_rollback_uses_move_only_and_never_deletes_source_or_target():
    start = PATCH.index("def _rollback_to_source")
    end = PATCH.index("def install_move_transaction_guard_v364")
    rollback = PATCH[start:end]
    assert "api.client.move_file(" in rollback
    assert "api._wait_item_visible(" in rollback
    assert "api.rename(restored, source_name)" in rollback
    assert "delete_file(" not in rollback
    assert ".delete(" not in rollback
    assert "已把文件安全恢复到原目录" in rollback


def test_v364_every_failed_move_path_registers_delete_protection_before_returning_none():
    move_start = PATCH.index("def move_item(")
    delete_start = PATCH.index("def delete(", move_start)
    move = PATCH[move_start:delete_start]
    # 回滚分支和普通失败/不确定分支都必须先登记保护，再把失败交回 MoviePilot。
    assert move.count("_protect_failed_move(") >= 2
    assert "后续 MoviePilot 失败清理不得删除该文件" in move
    assert "已冻结删除，禁止回收站清理" in move
    tail = move[move.rindex("_protect_failed_move("):]
    assert "return None" in tail


def test_v364_blocks_delete_schedule_and_irreversible_purge_for_protected_move():
    delete_start = PATCH.index("def delete(")
    schedule_start = PATCH.index("def schedule_purge(", delete_start)
    purge_start = PATCH.index("def purge(", schedule_start)
    patch_end = PATCH.index("GuangYaApi.move_item = move_item", purge_start)

    delete = PATCH[delete_start:schedule_start]
    schedule = PATCH[schedule_start:purge_start]
    purge = PATCH[purge_start:patch_end]

    assert "_protected_delete_record(self, fileitem)" in delete
    assert "避免进入回收站" in delete
    assert "return False" in delete
    assert "return previous_delete(self, fileitem)" in delete

    assert "_protected_delete_record(self, fileitem)" in schedule
    assert "已阻止移动失败项加入永久删除队列" in schedule
    assert "return previous_schedule_purge" in schedule

    assert "_protected_delete_record(self, fileitem)" in purge
    assert "拒绝清空回收站项目" in purge
    assert "return previous_purge" in purge


def test_v364_does_not_globally_disable_legitimate_delete_or_duplicate_cleanup():
    # 未命中保护记录必须继续原 delete；已确认重复资源删除仍由原业务层控制。
    assert "return previous_delete(self, fileitem)" in PATCH
    assert "正常手动删除、已确认重复副本删除等未命中保护记录的操作继续走原逻辑" in PATCH
    # MoviePilot V3 的存储选择和 delete handler 都复用插件当前 _guangya_api，保护记录不会落在旁路实例。
    assert "event_data.storage_oper = self._guangya_api" in LEGACY
    assert "return self._guangya_api.delete(fileitem)" in LEGACY


def test_v364_protection_matching_uses_identity_path_or_name_size_not_size_only():
    assert "if fileid and fileid in ids:" in PATCH
    assert "if path and path in paths:" in PATCH
    assert "if parent in parents and name in names:" in PATCH
    assert "expected_size" in PATCH
    target = PATCH[PATCH.index("def _target_candidate"):PATCH.index("def _protection_state")]
    assert "source_id" in target
    assert "fileid" in target
    assert "return matches[0] if len(matches) == 1 else None" in target
    assert "不做纯大小猜测" in target


def test_v364_protection_window_covers_delayed_permanent_delete_queue():
    assert "_PROTECT_SECONDS = 15 * 60" in PATCH
    assert '"expires_at": now + _PROTECT_SECONDS' in PATCH
    assert "_prune_protection(api)" in PATCH


def test_v364_does_not_reimplement_moviepilot_media_business_rules():
    for forbidden in (
        "target_directory",
        "rename_format",
        "category.yaml",
        "tmdbid=",
        "recognize_by_meta",
        "MediaType.TV",
        "MediaType.MOVIE",
    ):
        assert forbidden not in PATCH, forbidden


def test_v364_release_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "3.6.4"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.6.4"
    assert 'plugin_version = "3.6.4"' in ENTRY
    assert '?v=3.6.4' in REMOTE
    assert "v3.6.4" in plugin_meta["history"]


def test_v364_runtime_logs_expose_rescue_rollback_and_delete_block_states():
    for token in (
        "移动失败事务保护已启用",
        "移动自愈",
        "移动回滚",
        "移动失败项已进入删除保护区",
        "已阻止删除移动失败/状态不确定文件",
        "永久删除执行前再次命中移动失败保护",
    ):
        assert token in PATCH, token
