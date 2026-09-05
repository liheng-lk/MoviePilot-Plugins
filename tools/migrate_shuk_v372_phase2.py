from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
TESTS = ROOT / "tests" / "v3" / "shukguangyadisk"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def remove_function(text: str, name: str) -> str:
    marker = f"\ndef {name}("
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"function not found: {name}")
    end = text.find("\n\n__all__", start)
    if end < 0:
        raise RuntimeError(f"__all__ not found after: {name}")
    return text[:start] + text[end:]


# 1) candidate import side effects: remove two behavior installers.
path = PLUGIN / "organizer_candidate_filter.py"
text = path.read_text(encoding="utf-8")
for line in (
    "from .organizer_loss_guard_v349 import install_loss_guard_v349\n",
    "from .organizer_empty_folder_guard_v3410 import install_empty_folder_guard_v3410\n",
    "install_loss_guard_v349()\n",
    "install_empty_folder_guard_v3410()\n",
):
    if line not in text:
        raise RuntimeError(f"candidate token missing: {line.strip()}")
    text = text.replace(line, "", 1)
text = text.replace(
    "v3.7.1 起冲突策略、预览缺员补救和旧 preview retry 唤醒由 Execution 核心显式调用，不再修改 QueueRecovery/FolderStream 类。\n",
    "v3.7.1 起冲突策略、预览缺员补救和旧 preview retry 唤醒由 Execution 核心显式调用，不再修改 QueueRecovery/FolderStream 类。\n"
    "v3.7.2 起 loss guard 终态核对与 empty-folder 陈旧任务收口也由 Execution 显式负责，两个旧 installer 退出运行图。\n",
    1,
)
path.write_text(text, encoding="utf-8")

# 2) loss_guard becomes helper-only. Preserve preview/build/defer helpers, remove runtime class patching.
path = PLUGIN / "organizer_loss_guard_v349.py"
text = path.read_text(encoding="utf-8")
text = text.replace("from .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n", "", 1)
text = remove_function(text, "install_loss_guard_v349")
text = replace_once(
    text,
    '__all__ = ["install_loss_guard_v349"]',
    '__all__ = [\n    "_audit_preview",\n    "_build_moviepilot_kwargs",\n    "_defer_unconfirmed_members",\n    "_preview_result",\n]',
    "loss_guard __all__",
)
path.write_text(text, encoding="utf-8")

# 3) empty_folder becomes source-fact helper-only.
path = PLUGIN / "organizer_empty_folder_guard_v3410.py"
text = path.read_text(encoding="utf-8")
text = text.replace("from .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n", "", 1)
text = remove_function(text, "install_empty_folder_guard_v3410")
text = replace_once(
    text,
    '__all__ = ["install_empty_folder_guard_v3410"]',
    '__all__ = [\n    "_clear_stale_transient_state",\n    "_live_primary_media_state",\n    "_runtime_media_exts",\n]',
    "empty guard __all__",
)
path.write_text(text, encoding="utf-8")

# 4) explicit terminal reconciliation in final Execution core.
path = PLUGIN / "organizer_execution_v360.py"
text = path.read_text(encoding="utf-8")
anchor = "from .organizer_preview_retry_wakeup_v356 import _wake_legacy_preview_retries\n"
if "from .organizer_loss_guard_v349 import _defer_unconfirmed_members\n" not in text:
    text = replace_once(
        text,
        anchor,
        anchor + "from .organizer_loss_guard_v349 import _defer_unconfirmed_members\n",
        "execution import",
    )

old = '''        # 弱命名 envelope 已逐成员收口，禁止 Worker 外层再用聚合 True/False 覆盖成员结果。\n        if isinstance(item, _FolderBatchEnvelope) and not item.directory_mode:\n            logger.debug(\n                "【光鸭云盘助手】【v3.6.0】【最终结果】弱命名 envelope 已逐成员收口，跳过聚合 fallback: %s",\n                item.path,\n            )\n            return\n        return super()._fallback_terminal_state(item, success=success, message=message)\n'''
new = '''        # 弱命名 envelope 已逐成员收口，禁止 Worker 外层再用聚合 True/False 覆盖成员结果。\n        if isinstance(item, _FolderBatchEnvelope) and not item.directory_mode:\n            logger.debug(\n                "【光鸭云盘助手】【v3.6.0】【最终结果】弱命名 envelope 已逐成员收口，跳过聚合 fallback: %s",\n                item.path,\n            )\n            return\n\n        if isinstance(item, _FolderBatchEnvelope) and item.directory_mode:\n            # v3.7.2：空/已消失目录在 _execute_conflict_aware 已完成事实复核和 transient\n            # 清理，不能再进入“folder success 但无逐文件终态 -> deferred retry”。\n            if getattr(item, "_guangya_empty_folder_skip_v3410", False):\n                return\n\n            # Folder API 返回 success 不能推导“所有成员都成功”。只有 MoviePilot 的逐文件\n            # TransferComplete/history 才能终结成员；仍 inflight 的成员安全退回 deferred。\n            if success:\n                reason = "文件夹整理返回成功，但未收到该成员的 MoviePilot 单文件最终事件，已安全退回重试"\n                try:\n                    deferred = _defer_unconfirmed_members(self, item, reason)\n                except Exception as err:  # noqa: BLE001\n                    logger.exception(\n                        "【光鸭云盘助手】【数据安全校验】成员终态核对失败: %s - %s",\n                        item.path,\n                        err,\n                    )\n                    deferred = ["终态核对失败"]\n                    reason = f"成员终态核对失败：{err}"\n\n                if deferred:\n                    logger.error(\n                        "【光鸭云盘助手】【数据安全校验】文件夹存在 %s 个未确认成员，不标记完成，已退回重试: %s",\n                        len(deferred),\n                        item.path,\n                    )\n\n                self._append_monitor_history({\n                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),\n                    "path": item.path,\n                    "name": item.name,\n                    "size": item.size,\n                    "result": "folder_partial" if deferred else "folder_completed",\n                    "group_path": item.path,\n                    "group_name": item.name,\n                    "batch_id": item.batch_id,\n                    "message": (\n                        f"文件夹任务结束：成员 {len(item.members)}；"\n                        + (\n                            f"{len(deferred)} 个未收到单文件终态，已退回重试"\n                            if deferred\n                            else "所有成员均收到 MoviePilot 单文件终态"\n                        )\n                        + (f"；{message}" if message else "")\n                    ),\n                })\n                return\n\n        return super()._fallback_terminal_state(item, success=success, message=message)\n'''
text = replace_once(text, old, new, "execution fallback")
text = text.replace(
    '"organizer_policy_version": "v3.7.1"',
    '"organizer_policy_version": "v3.7.2"',
    1,
)
text = text.replace(
    "【光鸭云盘助手】【整理核心 v3.7.1】policy 执行链已显式接管：",
    "【光鸭云盘助手】【整理核心 v3.7.2】policy 执行链已显式接管：",
    1,
)
text = text.replace(
    "冲突处置/预览补救/版本 Rename/重复终态不再使用运行时 monkey patch",
    "冲突处置/预览补救/版本 Rename/重复终态/folder 终态核对不再使用运行时 monkey patch",
    1,
)
path.write_text(text, encoding="utf-8")

# 5) Add architecture contract for this migration. Existing versioned behavior tests remain as regression.
phase_test = TESTS / "test_organizer_phase2_v372_contract.py"
phase_test.write_text('''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"\nCANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")\nEXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\nLOSS = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")\nEMPTY = (PLUGIN / "organizer_empty_folder_guard_v3410.py").read_text(encoding="utf-8")\n\n\ndef test_v372_removes_loss_and_empty_runtime_installers():\n    for token in ("install_loss_guard_v349", "install_empty_folder_guard_v3410"):\n        assert token not in CANDIDATE\n        assert token not in LOSS\n        assert token not in EMPTY\n    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer" not in LOSS\n    assert "GuangYaQueueRecoveryMixin._fallback_terminal_state" not in LOSS\n    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer" not in EMPTY\n    assert "GuangYaQueueRecoveryMixin._fallback_terminal_state" not in EMPTY\n\n\ndef test_v372_execution_owns_folder_terminal_reconciliation():\n    for token in (\n        "_defer_unconfirmed_members(self, item, reason)",\n        "_guangya_empty_folder_skip_v3410",\n        '"folder_partial" if deferred else "folder_completed"',\n        '"organizer_policy_version": "v3.7.2"',\n    ):\n        assert token in EXECUTION, token\n\n\ndef test_v372_keeps_helpers_not_second_policy():\n    assert "def _audit_preview" in LOSS\n    assert "def _build_moviepilot_kwargs" in LOSS\n    assert "def _defer_unconfirmed_members" in LOSS\n    assert "def _live_primary_media_state" in EMPTY\n    assert "def _clear_stale_transient_state" in EMPTY\n    for source in (LOSS, EMPTY):\n        assert "FileDisposition" not in source\n        assert "organizer_policy" not in source\n''', encoding="utf-8")

print("v3.7.2 phase2 migration applied")
