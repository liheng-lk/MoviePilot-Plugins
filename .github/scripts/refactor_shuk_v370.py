from __future__ import annotations

from pathlib import Path

ROOT = Path("plugins.v3/shukguangyadisk")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise AssertionError(f"patch point changed: {label}")
    return text.replace(old, new, 1)


def patch_state() -> None:
    path = ROOT / "organizer_state.py"
    text = path.read_text(encoding="utf-8")
    needle = "        self.mutate(_apply)\n\n    def mark_blocked(\n"
    insert = '''        self.mutate(_apply)

    def mark_non_actionable(self, *, path: str, fingerprint: str) -> bool:
        """源仍存在但当前无法可靠识别/规划时原地停放；同指纹只记录一次。

        复用 ignored 持久槽以避免 schema 扩张；与 unsupported 的共同语义都是“当前内容不再
        自动提交”。文件指纹变化仍由 ``_drop_other_versions`` 自动重新开放。
        """

        def _apply(state: Dict[str, Any]) -> bool:
            self._drop_other_versions(state, path, fingerprint)
            existed = state["ignored"].get(path) == fingerprint
            state["ignored"][path] = fingerprint
            state["blocked"].pop(path, None)
            for name in ("stabilizing", "inflight", "retry"):
                state[name].pop(path, None)
            return not existed

        return bool(self.mutate(_apply))

    def retire_path(self, *, path: str) -> bool:
        """源已经被移动/删除后的唯一终态：从所有本地状态槽移除，不制造 completed 历史。"""

        def _apply(state: Dict[str, Any]) -> bool:
            removed = False
            for name in ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry"):
                mapping = state[name]
                if path in mapping:
                    mapping.pop(path, None)
                    removed = True
            return removed

        return bool(self.mutate(_apply))

    def mark_blocked(
'''
    path.write_text(replace_once(text, needle, insert, "state methods"), encoding="utf-8")


def patch_history() -> None:
    path = ROOT / "organizer_folder_history.py"
    text = path.read_text(encoding="utf-8")
    old = '''    _monitor_history_limit = 1000
    _folder_history_group_limit = 40
    _folder_history_detail_limit = 80
'''
    new = '''    _monitor_history_limit = 120
    _folder_history_group_limit = 12
    _folder_history_detail_limit = 20
    _history_compacted_v370: bool = False

    def init_organizer_monitor(self, *args: Any, **kwargs: Any):
        result = super().init_organizer_monitor(*args, **kwargs)
        if not self._history_compacted_v370:
            self._history_compacted_v370 = True
            raw = list(self.get_data(self._monitor_history_key) or [])
            compact = raw[-self._monitor_history_limit :]
            if len(compact) != len(raw):
                self.save_data(self._monitor_history_key, compact)
        return result
'''
    text = replace_once(text, old, new, "history limits")
    text = replace_once(
        text,
        'data["history"] = raw_history[-40:][::-1]',
        'data["history"] = raw_history[-20:][::-1]',
        "history api rows",
    )
    path.write_text(text, encoding="utf-8")


def patch_execution() -> None:
    path = ROOT / "organizer_execution_v360.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from __future__ import annotations\n\nfrom typing",
        "from __future__ import annotations\n\nimport time\nfrom typing",
        "execution time import",
    )
    old_import = '''from .organizer_source_terminal_v3618 import (
    SOURCE_MISSING_TERMINAL_V3618,
    confirm_source_missing_v3618,
    retire_missing_source_v3618,
    source_missing_hint_v3618,
)
'''
    new_import = '''from .organizer_policy import (
    FileDisposition,
    decide_failed_execution,
    should_probe_source_presence,
)
from .organizer_source_terminal_v3618 import (
    SOURCE_MISSING_TERMINAL_V3618,
    confirm_source_missing_v3618,
    probe_source_presence_v3618,
    retire_missing_source_v3618,
)
'''
    text = replace_once(text, old_import, new_import, "execution policy imports")
    old = '''        # 预检时源仍存在，但在进入 MoviePilot 后刚好被其它流程搬走时，MoviePilot 会返回
        # “没有找到可整理的媒体文件”。只有再次强制刷新确认真的不存在，才终态清理；
        # 网络/API失败或媒体过滤仍沿用原失败语义。
        if not success and source_missing_hint_v3618(message) and confirm_source_missing_v3618(self, item):
            subtree = bool(isinstance(item, _FolderBatchEnvelope) and item.directory_mode)
            retire_missing_source_v3618(self, item, subtree=subtree)
            return
'''
    new = '''        # v3.7 文件处理策略：只有语义可能依赖源存在性时才额外访问远端。
        # present + 明确认识失败 => 原地停放，不 move/delete/rename，也不进入 retry；
        # missing => 只退休本地状态；unknown => 保持普通 retry，网络异常绝不伪装成未识别。
        if not success and should_probe_source_presence(message):
            presence = probe_source_presence_v3618(self, item)
            disposition = decide_failed_execution(message, presence)
            if disposition == FileDisposition.RETIRE_MISSING:
                subtree = bool(isinstance(item, _FolderBatchEnvelope) and item.directory_mode)
                retire_missing_source_v3618(self, item, subtree=subtree)
                return
            if disposition == FileDisposition.LEAVE_UNRECOGNIZED:
                parked = 0
                for member in self._v360_members(item):
                    try:
                        member_path, fingerprint = self._v360_member_identity(member)
                    except Exception:
                        continue
                    if self._state().mark_non_actionable(path=member_path, fingerprint=fingerprint):
                        parked += 1
                if parked:
                    group_path = str(getattr(item, "path", "") or "")
                    self._append_monitor_history({
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "path": group_path,
                        "name": str(getattr(item, "name", "") or group_path.rsplit("/", 1)[-1]),
                        "size": int(getattr(item, "size", 0) or 0),
                        "result": "unrecognized_untouched",
                        "group_path": group_path if isinstance(item, _FolderBatchEnvelope) else "",
                        "message": f"MoviePilot 未形成可靠媒体/目标，源文件原地保留；成员={parked}；不进入重试",
                    })
                    logger.warning(
                        "【光鸭云盘助手】【整理策略】【未识别保留】源文件不移动、不删除、不改名、不重试: %s；%s",
                        group_path,
                        message,
                    )
                return
'''
    text = replace_once(text, old, new, "execution failure policy")
    path.write_text(text, encoding="utf-8")


def patch_partial_preview() -> None:
    path = ROOT / "organizer_preview_partial_v355.py"
    text = path.read_text(encoding="utf-8")
    old_import = "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n"
    new_import = '''from .organizer_policy import (
    FileDisposition,
    decide_failed_execution,
    should_probe_source_presence,
)
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_source_terminal_v3618 import (
    probe_source_presence_v3618,
    retire_missing_source_v3618,
)
'''
    text = replace_once(text, old_import, new_import, "partial preview policy imports")
    old_loop = '''    # 逐文件预览仍失败的成员单独隔离，不再把整个 Season 放回 retry。
    for path, reason in errors.items():
        _block_member(
            plugin,
            candidates[path],
            f"完整目录预览缺员，逐文件补预览仍无法确认：{reason}",
            result="preview_member_isolated",
        )
'''
    new_loop = '''    # 逐文件失败也统一交给 v3.7 policy：明确未识别原地停放；明确消失退休；
    # 网络/API等暂时失败保留 inflight，外层完成态会把它送回 retry；其它安全冲突才 blocked。
    unrecognized = missing_sources = transient_errors = blocked_errors = 0
    for path, reason in errors.items():
        member = candidates[path]
        if should_probe_source_presence(reason):
            presence = probe_source_presence_v3618(plugin, member)
            disposition = decide_failed_execution(reason, presence)
        else:
            disposition = FileDisposition.RETRY_TRANSIENT
        if disposition == FileDisposition.LEAVE_UNRECOGNIZED:
            fingerprint = plugin._fingerprint(member)
            if plugin._state().mark_non_actionable(path=path, fingerprint=fingerprint):
                plugin._append_monitor_history({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "path": path,
                    "name": str(getattr(member, "name", "") or PurePosixPath(path).name),
                    "size": int(getattr(member, "size", 0) or 0),
                    "result": "unrecognized_untouched",
                    "group_path": item.path,
                    "group_name": item.name,
                    "message": f"逐文件 MoviePilot 识别/预览无法形成可靠目标，源原地保留：{reason}",
                })
            unrecognized += 1
            continue
        if disposition == FileDisposition.RETIRE_MISSING:
            retire_missing_source_v3618(plugin, member)
            missing_sources += 1
            continue
        if disposition == FileDisposition.RETRY_TRANSIENT:
            transient_errors += 1
            continue
        blocked_errors += 1
        _block_member(
            plugin,
            member,
            f"完整目录预览缺员，逐文件补预览仍无法确认：{reason}",
            result="preview_member_isolated",
        )
'''
    text = replace_once(text, old_loop, new_loop, "partial preview failure loop")
    old_summary = '''            f"目录预览缺员已局部处理：逐文件确认={len(rows)}，实际整理={attempted}，"
            f"调用失败={call_failed}，单独隔离={len(errors) + len(collision_sources)}"
'''
    new_summary = '''            f"目录预览缺员已局部处理：逐文件确认={len(rows)}，实际整理={attempted}，"
            f"调用失败={call_failed}，未识别保留={unrecognized}，源消失={missing_sources}，"
            f"暂时失败={transient_errors}，安全阻断={blocked_errors + len(collision_sources)}"
'''
    text = replace_once(text, old_summary, new_summary, "partial preview history summary")
    old_log = '''        "调用失败=%s，隔离=%s；不再因单个缺员拖死整个资源",
        item.path,
        len(rows),
        attempted,
        call_failed,
        len(errors) + len(collision_sources),
'''
    new_log = '''        "调用失败=%s，未识别保留=%s，暂时失败=%s，安全阻断=%s；不再因单个缺员拖死整个资源",
        item.path,
        len(rows),
        attempted,
        call_failed,
        unrecognized,
        transient_errors,
        blocked_errors + len(collision_sources),
'''
    text = replace_once(text, old_log, new_log, "partial preview log summary")
    text = replace_once(
        text,
        'f"隔离 {len(errors) + len(collision_sources)}"',
        'f"未识别保留 {unrecognized}，暂时失败 {transient_errors}，安全阻断 {blocked_errors + len(collision_sources)}"',
        "partial preview result summary",
    )
    path.write_text(text, encoding="utf-8")


SINGLE_TARGET_HELPER = r'''
def _handle_single_existing_target(
    plugin: Any,
    item: _FolderBatchEnvelope,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    rows: Dict[str, Dict[str, Any]],
) -> Optional[Tuple[bool, str]]:
    """单主视频已存在最终目标时执行唯一大小策略；没有已有目标则返回 None。"""
    members = _member_map(plugin, item)
    if len(members) != 1:
        return None
    source, member = next(iter(members.items()))
    row = rows.get(source) or {}
    if not bool(row.get("success")):
        return None
    target = _norm(plugin, row.get("target"))
    if not target:
        return None
    api = getattr(plugin, "_guangya_api", None)
    if not api:
        return None
    try:
        existing = api.get_item(Path(target))
    except Exception as err:  # noqa: BLE001
        _mark_blocked(
            plugin,
            member,
            f"无法可靠读取 MoviePilot 最终目标，禁止覆盖/删除: {target} - {err}",
            result="existing_target_probe_blocked",
        )
        return True, "已有目标检查失败，源文件保持原位"
    if not existing:
        return None
    if str(getattr(existing, "type", "file") or "file") != "file":
        _mark_blocked(
            plugin,
            member,
            f"MoviePilot 最终目标已存在但不是文件: {target}",
            result="existing_target_probe_blocked",
        )
        return True, "已有目标类型异常，源文件保持原位"

    disposition = decide_existing_target(_member_size(member), _member_size(existing))
    if disposition == FileDisposition.BLOCK_SAFETY:
        _mark_blocked(
            plugin,
            member,
            f"已有目标但源/目标字节大小无法可靠取得，禁止自动删除或覆盖: {target}",
            result="existing_target_size_unknown",
        )
        return True, "已有目标大小未知，源文件保持原位"

    if disposition == FileDisposition.DELETE_DUPLICATE:
        try:
            refresh = getattr(api, "refresh_item", None)
            current_source = refresh(Path(source)) if callable(refresh) else api.get_item(Path(source))
            current_target = api.get_item(Path(target))
        except Exception as err:  # noqa: BLE001
            _mark_blocked(
                plugin,
                member,
                f"重复删除前复核失败，源文件保持原位: {err}",
                result="duplicate_delete_blocked",
            )
            return True, "重复删除前复核失败"
        if not current_source:
            retire = getattr(plugin._state(), "retire_path", None)
            if callable(retire):
                retire(path=source)
            return True, "重复源已不存在"
        if (
            not current_target
            or decide_existing_target(
                _member_size(current_source),
                _member_size(current_target),
            ) != FileDisposition.DELETE_DUPLICATE
        ):
            _mark_blocked(
                plugin,
                member,
                "重复删除前源/目标大小事实已变化，拒绝删除",
                result="duplicate_delete_blocked",
            )
            return True, "重复删除前事实变化"
        expected_fileid = str(getattr(member, "fileid", "") or "")
        current_fileid = str(getattr(current_source, "fileid", "") or "")
        if expected_fileid and current_fileid and expected_fileid != current_fileid:
            _mark_blocked(
                plugin,
                member,
                "重复删除前 fileId 已变化，拒绝删除",
                result="duplicate_delete_blocked",
            )
            return True, "重复删除前 fileId 变化"
        if not api.delete(current_source):
            _mark_blocked(
                plugin,
                member,
                "确认同大小重复，但移入回收站失败，源文件保持原位",
                result="duplicate_delete_blocked",
            )
            return True, "重复文件删除失败"
        retire = getattr(plugin._state(), "retire_path", None)
        if callable(retire):
            retire(path=source)
        plugin._append_monitor_history({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": source,
            "name": str(getattr(member, "name", "") or PurePosixPath(source).name),
            "size": int(_member_size(member) or 0),
            "result": "duplicate_deleted_existing_target",
            "group_path": item.path,
            "group_name": item.name,
            "message": f"MoviePilot 已确认最终目标且字节大小完全一致，重复源已安全移入回收站: {target}",
            "target": target,
        })
        logger.info(
            "【光鸭云盘助手】【整理策略】【同大小去重】目标已存在且字节完全一致，删除重复源: %s -> %s",
            source,
            target,
        )
        return True, "同大小重复源已删除"

    numbers = _next_version_numbers(plugin, target, 1)
    if not numbers:
        _mark_blocked(
            plugin,
            member,
            f"已有目标大小不同，但无法可靠分配版本号: {target}",
            result="version_target_blocked",
        )
        return True, "不同大小版本无法分配版本号"
    version = numbers[0]
    version_target, error = _single_preview_target(
        plugin,
        transfer_chain,
        base_kwargs,
        member,
        version,
    )
    if not version_target or f"版本{version}" not in PurePosixPath(version_target).stem:
        _mark_blocked(
            plugin,
            member,
            error or "不同大小版本未形成唯一版本目标",
            result="version_target_blocked",
        )
        return True, "版本目标预览失败"
    try:
        version_existing = api.get_item(Path(version_target))
    except Exception as err:  # noqa: BLE001
        _mark_blocked(
            plugin,
            member,
            f"无法确认版本目标是否存在: {version_target} - {err}",
            result="version_target_blocked",
        )
        return True, "版本目标检查失败"
    if version_existing:
        _mark_blocked(
            plugin,
            member,
            f"版本目标已存在，拒绝覆盖: {version_target}",
            result="version_target_blocked",
        )
        return True, "版本目标已存在"
    logger.info(
        "【光鸭云盘助手】【整理策略】【不同大小多版本】原目标已存在但大小不同，保留为版本%s: %s -> %s",
        version,
        source,
        version_target,
    )
    return _execute_member(plugin, transfer_chain, base_kwargs, member, version)


'''


def patch_conflict() -> None:
    path = ROOT / "organizer_conflict_resolution_v353.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n",
        "from .organizer_policy import FileDisposition, decide_existing_target\nfrom .organizer_queue_recovery import GuangYaQueueRecoveryMixin\n",
        "conflict policy import",
    )
    text = replace_once(
        text,
        "def _block_guard_failure(\n",
        SINGLE_TARGET_HELPER + "def _block_guard_failure(\n",
        "single existing target helper",
    )
    old_rows = '''    rows, row_error = _preview_member_rows(plugin, item, preview)
    if row_error:
        return _block_guard_failure(plugin, item, row_error, details)

    collisions = _collision_groups(plugin, item, rows)
'''
    new_rows = '''    rows, row_error = _preview_member_rows(plugin, item, preview)
    if row_error:
        return _block_guard_failure(plugin, item, row_error, details)

    # v3.7 补齐旧 v3.5.3 只处理“同批多个源撞目标”的缺口：单个新文件如果 MoviePilot
    # 最终目标已经存在，也必须先按统一大小策略决定去重或多版本，禁止直接交给 overwrite。
    if safe and len(list(getattr(item, "members", None) or [])) == 1:
        handled = _handle_single_existing_target(plugin, item, transfer_chain, kwargs, rows)
        if handled is not None:
            return handled

    collisions = _collision_groups(plugin, item, rows)
'''
    text = replace_once(text, old_rows, new_rows, "existing target dispatch")
    old_install = '''        # 单主视频不可能发生“本批多个源映射同目标”，继续原有最快路径。
        if len(list(getattr(item, "members", None) or [])) < 2:
            return previous_execute(self, item)
        return _execute_conflict_aware(self, item)
'''
    new_install = '''        # v3.7 起单主视频也进入同一 policy：它可能与媒体库已有最终目标发生冲突。
        return _execute_conflict_aware(self, item)
'''
    text = replace_once(text, old_install, new_install, "single member conflict routing")
    text = text.replace(
        'plugin._state().mark_completed(path=path, fingerprint=str(record.get("fingerprint") or ""))',
        'plugin._state().retire_path(path=path)',
    )
    path.write_text(text, encoding="utf-8")


def patch_architecture() -> None:
    rules = ROOT / "ORGANIZER_RULES.md"
    rules.write_text(
        """# 光鸭云盘助手自动整理不可变规则

本文件从 v3.7.0 起是自动整理功能的行为契约。后续任何修复先修改/验证这里的规则，禁止用新的版本补丁模块绕开这些约束。

## 一条流水线

`发现 → 稳定确认 → MoviePilot 识别/预览 → organizer_policy 决策 → 执行 → 终态/简洁日志`

### 文件处理矩阵

| MoviePilot/远端事实 | 决策 | 允许的动作 |
| --- | --- | --- |
| 识别成功、目标可靠、目标不存在 | ORGANIZE | 按 MoviePilot 规划精准整理 |
| 识别失败且源确认仍存在 | LEAVE_UNRECOGNIZED | 原地保留；不移动、不删除、不改名、不 retry |
| 识别失败但源存在性未知 | RETRY_TRANSIENT | 仅退避重试，不做文件写操作 |
| 源明确不存在 | RETIRE_MISSING | 只清本地调度状态 |
| 最终目标已存在，双方字节大小已知且完全相同 | DELETE_DUPLICATE | 删除源重复文件；删除前再次核对大小/fileId |
| 最终目标已存在，双方字节大小已知且不同 | ORGANIZE_VERSION | 生成稳定版本名后二次 preview，确认唯一再整理 |
| 任一大小未知 | BLOCK_SAFETY | 不删除、不覆盖，源保持原位 |

## 不允许破坏的边界

1. 媒体身份、分类目录、普通重命名模板、目标存储、move/copy、刮削仍由 MoviePilot 决定。
2. 光鸭插件只在“安全终态”上补充：识别失败原地停放、同大小去重、不同大小多版本、远端真实性确认。
3. 删除必须有比“文件名相同”更强的证据：MoviePilot 已确认同一最终目标 + 两边精确字节大小相同 + 删除前二次远端核验。
4. 未识别文件不是失败队列任务。内容不变时只记录一次；文件指纹变化后可以重新进入识别。
5. `completed` 是短期调度缓存，不是历史数据库；真正整理历史属于 MoviePilot。光鸭 UI 只保留有限的近期流水。
6. 网络/API异常永远不能转换成“文件不存在”“未识别”或“重复”。

## 重构约束

v3.6 及更早的 `install_*_vXXXX()` 图从这里起冻结：**不得继续新增同类行为补丁**。

后续分阶段把旧能力迁入五层核心：

1. `discovery`：发现/分页/稳定性；
2. `recognition`：MoviePilot 身份与 preview；
3. `organizer_policy.py`：唯一文件决策；
4. `executor`：光鸭 move/delete/version 与真实性确认；
5. `state/reporting`：仅活动调度状态 + 有界近期日志。

每迁移一个旧 installer，必须先有等价行为测试，再删除旧安装入口；禁止“新核心 + 旧补丁同时各做一遍”。
""",
        encoding="utf-8",
    )
    path = ROOT / "ARCHITECTURE.md"
    text = path.read_text(encoding="utf-8")
    banner = "> **v3.7 重构规则**：自动整理的文件终态统一由 `organizer_policy.py` 决定，详细不可变规则见 `ORGANIZER_RULES.md`。v3.6 以前的 `install_*_vXXXX()` 行为图已冻结，不再新增版本补丁；后续只允许把已有能力逐步迁移进 discovery / recognition / policy / executor / state-reporting 五层核心。\n\n"
    if banner not in text:
        text = text.replace("# 光鸭云盘助手 V3 架构\n\n", "# 光鸭云盘助手 V3 架构\n\n" + banner, 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_state()
    patch_history()
    patch_execution()
    patch_partial_preview()
    patch_conflict()
    patch_architecture()


if __name__ == "__main__":
    main()
