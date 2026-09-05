from __future__ import annotations

from pathlib import Path

ROOT = Path("plugins.v3/shukguangyadisk")
TEST = Path("tests/v3/shukguangyadisk")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise AssertionError(f"patch point changed: {label}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, new: str, label: str) -> str:
    i = text.find(start)
    j = text.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError(f"section changed: {label}")
    return text[:i] + new + text[j:]


# 1) Conflict module: pure policy helpers only; no class monkey-patching.
path = ROOT / "organizer_conflict_resolution_v353.py"
text = read(path)
for old in (
    "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n",
    "from .organizer_recognition import GuangYaOrganizerMixin as GuangYaRecognitionMixin\n",
    "from .organizer_runtime import organizer_runtime_bound_to\n",
):
    text = text.replace(old, "")

rename_helper = '''def apply_version_rename_event(plugin: Any, event: Any) -> None:\n    \"\"\"Apply the current thread-local version suffix to MoviePilot TransferRename.\"\"\"\n    context = getattr(_RENAME_CONTEXT, \"value\", None)\n    if not isinstance(context, dict) or context.get(\"plugin_id\") != id(plugin):\n        return\n    data = getattr(event, \"event_data\", None)\n    source_item = getattr(data, \"source_item\", None) if data is not None else None\n    if not source_item:\n        return\n    storage = str(getattr(source_item, \"storage\", \"\") or \"\")\n    valid_storages = {str(getattr(plugin, \"_disk_name\", \"\") or \"\")}\n    names_getter = getattr(plugin, \"_storage_names\", None)\n    if callable(names_getter):\n        try:\n            valid_storages.update(str(value) for value in (names_getter() or set()))\n        except Exception:\n            pass\n    if storage not in valid_storages:\n        return\n\n    source = _norm(plugin, getattr(source_item, \"path\", \"\") or getattr(data, \"source_path\", \"\"))\n    primary = str(context.get(\"source\") or \"\")\n    if source != primary and PurePosixPath(source).parent != PurePosixPath(primary).parent:\n        return\n    render_str = str(getattr(data, \"render_str\", \"\") or \"\")\n    if not render_str:\n        return\n    updated = _apply_version_to_render(render_str, int(context[\"version\"]))\n    data.updated = True\n    data.updated_str = updated\n    data.source = \"光鸭云盘助手-policy\"\n\n\n'''
text = replace_section(
    text,
    "def _install_rename_handler() -> None:\n",
    "def _single_preview_target(\n",
    rename_helper,
    "conflict rename installer",
)

terminal_helper = '''def handle_duplicate_terminal_event(plugin: Any, event: Any, success: bool) -> None:\n    \"\"\"Consume duplicate waiters after the normal terminal/history chain has completed.\"\"\"\n    payload_getter = getattr(plugin, \"_event_payload\", None)\n    payload = payload_getter(event) if callable(payload_getter) else {}\n    fileitem = payload.get(\"fileitem\") if isinstance(payload, dict) else None\n    source = _norm(plugin, getattr(fileitem, \"path\", \"\")) if fileitem else \"\"\n    history_id = payload.get(\"transfer_history_id\") if isinstance(payload, dict) else None\n    if not source:\n        return\n    with _PENDING_LOCK:\n        records = _PENDING_DUPLICATES.pop(source, [])\n    if not records:\n        return\n    if not success or not history_id:\n        logger.warning(\n            \"【光鸭云盘助手】【重复资源】保留副本未取得成功 history_id，不删除任何重复源: %s\",\n            source,\n        )\n        return\n    threading.Thread(\n        target=_delete_duplicate_worker,\n        args=(plugin, source, int(history_id), records),\n        name=f\"guangya-duplicate-cleanup-{int(time.time())}\",\n        daemon=True,\n    ).start()\n\n\n'''
text = replace_section(
    text,
    "def _install_terminal_duplicate_cleanup() -> None:\n",
    "def install_conflict_resolution_v353() -> None:\n",
    terminal_helper,
    "duplicate terminal installer",
)

install_start = text.find("def install_conflict_resolution_v353() -> None:\n")
all_start = text.find("__all__ = [", install_start)
if install_start < 0 or all_start < 0:
    raise AssertionError("conflict installer tail changed")
text = text[:install_start] + '''__all__ = [\n    \"_execute_conflict_aware\",\n    \"_execute_member\",\n    \"apply_version_rename_event\",\n    \"handle_duplicate_terminal_event\",\n    \"_apply_version_to_render\",\n    \"_episode_identity\",\n    \"_group_unique_representatives\",\n]\n'''
write(path, text)

# 2) Preview partial: pure rescue helper, no QueueRecovery mutation.
path = ROOT / "organizer_preview_partial_v355.py"
text = read(path)
text = text.replace("from .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n", "")
text = text.replace("【光鸭云盘助手】【v3.5.5】【预览局部补救】", "【光鸭云盘助手】【整理策略】【预览局部补救】")
helper = '''def rescue_partial_preview_if_needed(\n    plugin: Any,\n    item: Any,\n    result: Tuple[bool, str],\n) -> Tuple[bool, str]:\n    \"\"\"Rescue only the historical MoviePilot folder-preview missing-member failure.\"\"\"\n    if not isinstance(item, _FolderBatchEnvelope):\n        return result\n    try:\n        success, message = result\n    except Exception:\n        return result\n    if success or _MISSING_PREVIEW_TOKEN not in str(message or \"\"):\n        return result\n    logger.warning(\n        \"【光鸭云盘助手】【整理策略】【预览局部补救】完整目录预览存在缺员，\"\n        \"切换为同一 MoviePilot 上下文逐文件补预览: %s\",\n        item.path,\n    )\n    try:\n        return _rescue_partial_preview(plugin, item)\n    except Exception as err:  # noqa: BLE001\n        logger.exception(\n            \"【光鸭云盘助手】【整理策略】【预览局部补救】执行异常，保持原失败语义: %s - %s\",\n            item.path,\n            err,\n        )\n        return result\n\n\n__all__ = [\"rescue_partial_preview_if_needed\", \"_rescue_partial_preview\"]\n'''
start = text.find("def install_preview_partial_v355() -> None:\n")
if start < 0:
    raise AssertionError("preview partial installer changed")
text = text[:start] + helper
write(path, text)

# 3) Preview retry wakeup: retain migration helper but remove scan monkey-patch.
path = ROOT / "organizer_preview_retry_wakeup_v356.py"
text = read(path)
text = text.replace("from .organizer_folder_stream import GuangYaFolderStreamMixin\n\n", "")
start = text.find("def install_preview_retry_wakeup_v356() -> None:\n")
if start < 0:
    raise AssertionError("preview wakeup installer changed")
text = text[:start] + '__all__ = ["_wake_legacy_preview_retries"]\n'
write(path, text)

# 4) Candidate filter no longer installs policy/preview behavior patches.
path = ROOT / "organizer_candidate_filter.py"
text = read(path)
for old in (
    "from .organizer_conflict_resolution_v353 import install_conflict_resolution_v353\n",
    "from .organizer_preview_partial_v355 import install_preview_partial_v355\n",
    "from .organizer_preview_retry_wakeup_v356 import install_preview_retry_wakeup_v356\n",
):
    if old not in text:
        raise AssertionError(f"candidate import missing: {old.strip()}")
    text = text.replace(old, "")
for old in (
    '# v3.5.3 最后只处理 MP 已明确产生的重复目标，不改变普通命名/分类路径。\ninstall_conflict_resolution_v353()\n',
    '# v3.5.5 处理新的目录 preview 缺员：不放宽安全校验，只把异常成员局部隔离。\ninstall_preview_partial_v355()\n',
    '# v3.5.6 唤醒升级前已经进入 retry 的同类错误，让 v3.5.5 立即获得执行机会。\ninstall_preview_retry_wakeup_v356()\n',
):
    if old not in text:
        raise AssertionError(f"candidate installer block missing: {old.splitlines()[0]}")
    text = text.replace(old, "")
text = text.replace(
    "v3.6.3 在最终 MoviePilot kwargs 上增加 TV→MOVIE 安全消歧，仅对单主视频、无集号、非 Season 目录生效。\n",
    "v3.6.3 在最终 MoviePilot kwargs 上增加 TV→MOVIE 安全消歧，仅对单主视频、无集号、非 Season 目录生效。\n"
    "v3.7.1 起冲突策略、预览缺员补救和旧 preview retry 唤醒由 Execution 核心显式调用，不再修改 QueueRecovery/FolderStream 类。\n",
)
write(path, text)

# 5) Execution owns policy execution/events explicitly.
path = ROOT / "organizer_execution_v360.py"
text = read(path)
anchor = "from .organizer_folder_batch_v342 import _FolderBatchEnvelope\n"
imports = '''from .organizer_conflict_resolution_v353 import (\n    _execute_conflict_aware,\n    apply_version_rename_event,\n    handle_duplicate_terminal_event,\n)\nfrom .organizer_preview_partial_v355 import rescue_partial_preview_if_needed\nfrom .organizer_preview_retry_wakeup_v356 import _wake_legacy_preview_retries\n'''
if imports not in text:
    text = replace_once(text, anchor, anchor + imports, "execution policy imports")

text = replace_once(
    text,
    "    _v3617_blocked_diag_logged: bool = False\n",
    "    _v3617_blocked_diag_logged: bool = False\n"
    "    _v371_policy_banner_logged: bool = False\n"
    "    _v371_preview_retry_migration_checked: bool = False\n",
    "execution phase2 flags",
)

old_init_tail = '''        result = super().init_organizer_monitor()\n        if not self._v3617_blocked_diag_logged:\n'''
new_init_tail = '''        if not self._v371_preview_retry_migration_checked:\n            self._v371_preview_retry_migration_checked = True\n            try:\n                _wake_legacy_preview_retries(self)\n            except Exception as err:  # noqa: BLE001 - migration must never block monitor init\n                logger.warning("【光鸭云盘助手】【整理核心】旧 preview retry 状态迁移失败，保留原状态: %s", err)\n        if not self._v371_policy_banner_logged:\n            self._v371_policy_banner_logged = True\n            logger.info(\n                "【光鸭云盘助手】【整理核心 v3.7.1】policy 执行链已显式接管："\n                "冲突处置/预览补救/版本 Rename/重复终态不再使用运行时 monkey patch"\n            )\n\n        result = super().init_organizer_monitor()\n        if not self._v3617_blocked_diag_logged:\n'''
text = replace_once(text, old_init_tail, new_init_tail, "execution init direct migration")

old_directory = '''        if item.directory_mode:\n            if confirm_source_missing_v3618(self, item):\n                retire_missing_source_v3618(self, item, subtree=True)\n                return True, SOURCE_MISSING_TERMINAL_V3618\n            # 原生目录模式继续经过现有 loss-guard / conflict / season 等 MoviePilot 安全链。\n            return super()._execute_isolated_transfer(item)\n'''
new_directory = '''        if item.directory_mode:\n            if confirm_source_missing_v3618(self, item):\n                retire_missing_source_v3618(self, item, subtree=True)\n                return True, SOURCE_MISSING_TERMINAL_V3618\n            # v3.7.1：FolderBatch 的 policy/preview 链由执行核心显式调用，不再依赖\n            # organizer_conflict_resolution/preview_partial 对 QueueRecoveryMixin 的运行时改写。\n            result = _execute_conflict_aware(self, item)\n            return rescue_partial_preview_if_needed(self, item, result)\n'''
text = replace_once(text, old_directory, new_directory, "execution folder policy")

insert_before = "    def _fallback_terminal_state(self, item: Any, success: bool, message: str) -> None:\n"
methods = '''    def organizer_transfer_rename(self, event: Any) -> None:\n        \"\"\"MoviePilot TransferRename bridge for policy-managed version suffixes.\"\"\"\n        apply_version_rename_event(self, event)\n\n    def _record_terminal_transfer(self, event: Any, success: bool) -> None:\n        \"\"\"Keep normal terminal/history semantics, then consume duplicate waiters.\"\"\"\n        super()._record_terminal_transfer(event, success)\n        handle_duplicate_terminal_event(self, event, success)\n\n'''
if methods not in text:
    text = replace_once(text, insert_before, methods + insert_before, "execution direct event methods")
text = text.replace(
    '            "organizer_policy_version": "v3.7.0",',
    '            "organizer_policy_version": "v3.7.1",',
)
write(path, text)

# 6) Architecture contract: explicit migration progress.
path = ROOT / "ORGANIZER_RULES.md"
text = read(path)
append = '''\n## Phase 2 migration rule\n\n从 v3.7.1 开始，文件处置相关能力必须由最终 MRO 中的执行核心显式调用。\n`organizer_conflict_resolution_v353.py` 与 `organizer_preview_partial_v355.py` 只允许保留纯函数/纯 helper，\n不得再修改 `GuangYaQueueRecoveryMixin`、`GuangYaFolderStreamMixin` 或 `GuangYaOrganizerMixin` 的类方法。\n旧状态迁移可以保留兼容 helper，但必须由生命周期入口显式调用一次，禁止通过扫描 monkey patch 隐式执行。\n'''
if "## Phase 2 migration rule" not in text:
    text = text.rstrip() + append
write(path, text)

# 7) Update old tests from installer-order contracts to explicit-core contracts.
path = TEST / "test_conflict_resolution_v353.py"
text = read(path)
text = text.replace(
    '    record_tail = PATCH[PATCH.index("def record(self: Any, event: Any, success: bool)") :]\n',
    '    record_tail = PATCH[PATCH.index("def handle_duplicate_terminal_event(plugin: Any, event: Any, success: bool)") :]\n',
)
text = text.replace(
    '''def test_conflict_resolver_is_final_scheduler_patch():\n    assert "from .organizer_conflict_resolution_v353 import install_conflict_resolution_v353" in FILTER\n    assert "install_conflict_resolution_v353()" in FILTER\n    assert FILTER.index("install_task_semantics_v352()") < FILTER.index("install_conflict_resolution_v353()")\n''',
    '''def test_conflict_resolver_is_called_explicitly_by_execution_core_without_monkey_patch():\n    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\n    assert "install_conflict_resolution_v353" not in FILTER\n    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute" not in PATCH\n    assert "_execute_conflict_aware(self, item)" in execution\n    assert "apply_version_rename_event(self, event)" in execution\n    assert "handle_duplicate_terminal_event(self, event, success)" in execution\n''',
)
write(path, text)

path = TEST / "test_preview_partial_v355.py"
text = read(path)
text = text.replace("'_rescue_partial_preview(self, item)'", "'_rescue_partial_preview(plugin, item)'")
text = text.replace(
    '''def test_v355_installs_after_v354_completion_evidence_layer():\n    reconcile_pos = CANDIDATE.index('install_completion_reconcile_v354()')\n    rescue_pos = CANDIDATE.index('install_preview_partial_v355()')\n    assert rescue_pos > reconcile_pos\n    assert 'from .organizer_preview_partial_v355 import install_preview_partial_v355' in CANDIDATE\n''',
    '''def test_preview_rescue_is_explicit_execution_helper_not_queue_monkey_patch():\n    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\n    assert "install_preview_partial_v355" not in CANDIDATE\n    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute" not in PATCH\n    assert "rescue_partial_preview_if_needed(self, item, result)" in execution\n''',
)
text = text.replace("'【v3.5.5】【预览局部补救】'", "'【整理策略】【预览局部补救】'")
write(path, text)

path = TEST / "test_preview_retry_wakeup_v356.py"
text = read(path)
text = text.replace("CANDIDATE = (PLUGIN / \"organizer_candidate_filter.py\").read_text(encoding=\"utf-8\")\n", "EXECUTION = (PLUGIN / \"organizer_execution_v360.py\").read_text(encoding=\"utf-8\")\n")
text = text.replace(
    '''def test_v356_runs_once_before_each_scan_then_persists_marker():\n    for token in (\n        '_MARKER_KEY = "organize_v356_preview_retry_wakeup"',\n        'if isinstance(marker, dict) and marker.get("applied"):',\n        'plugin.save_data(_MARKER_KEY, marker)',\n        '_wake_legacy_preview_retries(self)',\n        'return previous_scan(self, manual=manual)',\n    ):\n        assert token in PATCH, token\n\n\ndef test_v356_installs_after_v355_rescue_layer():\n    rescue_pos = CANDIDATE.index('install_preview_partial_v355()')\n    wake_pos = CANDIDATE.index('install_preview_retry_wakeup_v356()')\n    assert wake_pos > rescue_pos\n    assert 'from .organizer_preview_retry_wakeup_v356 import install_preview_retry_wakeup_v356' in CANDIDATE\n''',
    '''def test_v356_migration_is_marker_guarded_and_called_explicitly_once_from_execution_init():\n    for token in (\n        '_MARKER_KEY = "organize_v356_preview_retry_wakeup"',\n        'if isinstance(marker, dict) and marker.get("applied"):',\n        'plugin.save_data(_MARKER_KEY, marker)',\n    ):\n        assert token in PATCH, token\n    assert "install_preview_retry_wakeup_v356" not in PATCH\n    assert "_v371_preview_retry_migration_checked" in EXECUTION\n    assert "_wake_legacy_preview_retries(self)" in EXECUTION\n''',
)
write(path, text)

path = TEST / "test_completion_reconcile_v354.py"
text = read(path)
text = text.replace(
    '''def test_v354_runs_after_existing_single_flight_sticky_and_conflict_layers():\n    conflict_pos = CANDIDATE.index('install_conflict_resolution_v353()')\n    reconcile_pos = CANDIDATE.index('install_completion_reconcile_v354()')\n    assert reconcile_pos > conflict_pos\n    assert 'from .organizer_completion_reconcile_v354 import install_completion_reconcile_v354' in CANDIDATE\n''',
    '''def test_v354_legacy_completion_migration_remains_but_no_longer_depends_on_conflict_installer_order():\n    assert 'install_completion_reconcile_v354()' in CANDIDATE\n    assert 'install_conflict_resolution_v353()' not in CANDIDATE\n    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\n    assert '_execute_conflict_aware(self, item)' in execution\n''',
)
write(path, text)

# New phase-2 contract.
path = TEST / "test_organizer_phase2_v371_contract.py"
write(path, '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"\nCANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")\nEXECUTION = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\nCONFLICT = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")\nPREVIEW = (PLUGIN / "organizer_preview_partial_v355.py").read_text(encoding="utf-8")\nWAKE = (PLUGIN / "organizer_preview_retry_wakeup_v356.py").read_text(encoding="utf-8")\nRULES = (PLUGIN / "ORGANIZER_RULES.md").read_text(encoding="utf-8")\n\n\ndef test_phase2_removes_three_runtime_behavior_installers():\n    for token in (\n        "install_conflict_resolution_v353",\n        "install_preview_partial_v355",\n        "install_preview_retry_wakeup_v356",\n    ):\n        assert token not in CANDIDATE\n    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute" not in CONFLICT\n    assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute" not in PREVIEW\n    assert "GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan" not in WAKE\n\n\ndef test_execution_core_explicitly_owns_policy_preview_and_events():\n    for token in (\n        "_execute_conflict_aware(self, item)",\n        "rescue_partial_preview_if_needed(self, item, result)",\n        "apply_version_rename_event(self, event)",\n        "handle_duplicate_terminal_event(self, event, success)",\n        "_wake_legacy_preview_retries(self)",\n        '"organizer_policy_version": "v3.7.1"',\n    ):\n        assert token in EXECUTION, token\n\n\ndef test_phase2_helpers_do_not_import_runtime_classes_to_patch():\n    for source in (CONFLICT, PREVIEW, WAKE):\n        assert "._execute_isolated_transfer =" not in source\n        assert ".run_organize_monitor_scan =" not in source\n    assert "不得再修改" in RULES\n''')

print("v3.7.1 phase2 migration staged")
