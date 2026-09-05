from pathlib import Path

PATH = Path("plugins.v3/shukguangyadisk/organizer_conflict_resolution_v353.py")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise AssertionError(f"patch point changed: {label}")
    text = text.replace(old, new, 1)


replace_once(
    "import re\nimport threading",
    "import copy\nimport re\nimport threading",
    "copy import",
)

replace_once(
    '''def _handle_single_existing_target(
    plugin: Any,
    item: _FolderBatchEnvelope,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    rows: Dict[str, Dict[str, Any]],
) -> Optional[Tuple[bool, str]]:
''',
    '''def _handle_single_existing_target(
    plugin: Any,
    item: _FolderBatchEnvelope,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    rows: Dict[str, Dict[str, Any]],
    *,
    forced_version: Optional[int] = None,
) -> Optional[Tuple[bool, str]]:
''',
    "single helper signature",
)

replace_once(
    '''    numbers = _next_version_numbers(plugin, target, 1)
    if not numbers:
        _mark_blocked(
            plugin,
            member,
            f"已有目标大小不同，但无法可靠分配版本号: {target}",
            result="version_target_blocked",
        )
        return True, "不同大小版本无法分配版本号"
    version = numbers[0]
''',
    '''    if forced_version is None:
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
    else:
        version = int(forced_version)
''',
    "forced version selection",
)

marker = "\ndef _block_guard_failure(\n"
if marker not in text:
    raise AssertionError("batch helper insertion point changed")

batch_helper = r'''
def _handle_existing_target_groups(
    plugin: Any,
    item: _FolderBatchEnvelope,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    rows: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """对预览中的每个最终目标统一应用已有目标策略。

    只要远端目标已经存在，该目标下的所有源成员都在这里收口；目标不存在的成员原样留给
    后续 MoviePilot 原生批处理/现有批内冲突消歧。相同已有目标下多个不同大小源会一次性
    预分配互不重复的版本号，避免同一批成员各自看到相同“下一个版本”。
    """
    members = _member_map(plugin, item)
    by_target: Dict[str, List[str]] = defaultdict(list)
    for source, row in rows.items():
        if source not in members or not bool((row or {}).get("success")):
            continue
        target = _norm(plugin, (row or {}).get("target"))
        if target:
            by_target[target].append(source)

    api = getattr(plugin, "_guangya_api", None)
    if not api:
        return {"handled": set(), "failed": 0, "blocked": 0, "target_groups": 0}

    handled: set[str] = set()
    failed = blocked = target_groups = 0
    for target, sources in sorted(by_target.items()):
        try:
            existing = api.get_item(Path(target))
        except Exception as err:  # noqa: BLE001 - 目标存在性不确定时 fail closed
            reason = f"无法可靠读取 MoviePilot 最终目标，禁止覆盖/删除: {target} - {err}"
            for source in sources:
                member = members[source]
                _mark_blocked(plugin, member, reason, result="existing_target_probe_blocked")
                handled.add(source)
                blocked += 1
            target_groups += 1
            continue
        if not existing:
            continue

        target_groups += 1
        target_size = _member_size(existing)
        version_sources = [
            source
            for source in sources
            if _member_size(members[source]) is not None
            and target_size is not None
            and _member_size(members[source]) != target_size
        ]
        version_map: Dict[str, int] = {}
        if version_sources:
            numbers = _next_version_numbers(plugin, target, len(version_sources))
            if not numbers:
                for source in version_sources:
                    _mark_blocked(
                        plugin,
                        members[source],
                        f"已有目标大小不同，但无法可靠分配唯一版本号: {target}",
                        result="version_target_blocked",
                    )
                    handled.add(source)
                    blocked += 1
            else:
                version_map = dict(zip(version_sources, numbers))

        for source in sorted(sources, key=lambda value: _member_sort_key(members[value], value)):
            if source in handled:
                continue
            member = members[source]
            shadow = copy.copy(item)
            shadow.members = [member]
            shadow.size = int(_member_size(member) or 0)
            result = _handle_single_existing_target(
                plugin,
                shadow,
                transfer_chain,
                base_kwargs,
                {source: rows[source]},
                forced_version=version_map.get(source),
            )
            # 目标可能在组级读取和成员二次读取之间消失；这种情况不算 handled，交回正常整理。
            if result is None:
                continue
            handled.add(source)
            if not bool(result[0]):
                failed += 1

    return {
        "handled": handled,
        "failed": failed,
        "blocked": blocked,
        "target_groups": target_groups,
    }


'''
text = text.replace(marker, "\n" + batch_helper + "def _block_guard_failure(\n", 1)

old_dispatch = '''    # v3.7 补齐旧 v3.5.3 只处理“同批多个源撞目标”的缺口：单个新文件如果 MoviePilot
    # 最终目标已经存在，也必须先按统一大小策略决定去重或多版本，禁止直接交给 overwrite。
    if safe and len(list(getattr(item, "members", None) or [])) == 1:
        handled = _handle_single_existing_target(plugin, item, transfer_chain, kwargs, rows)
        if handled is not None:
            return handled

    collisions = _collision_groups(plugin, item, rows)
'''
new_dispatch = '''    # v3.7 先把“媒体库已有最终目标”作为比批内碰撞更高优先级的事实处理。
    # 这样 Season 批次里的每一集都遵守同一条规则，而不是只有单文件任务才检查目标已存在。
    existing_handled: set[str] = set()
    if safe:
        existing_result = _handle_existing_target_groups(plugin, item, transfer_chain, kwargs, rows)
        existing_handled = set(existing_result.get("handled") or set())
        if existing_handled:
            remaining = [
                member
                for member in list(getattr(item, "members", None) or [])
                if _norm(plugin, getattr(member, "path", "")) not in existing_handled
            ]
            if not remaining:
                return True, (
                    f"已有目标策略已收口全部成员={len(existing_handled)}；"
                    "同大小重复已删除，不同大小已版本化或安全阻断"
                )
            # 原始目录任务不能再包含已经删除/版本化/阻断的成员；剩余成员继续沿用同一
            # MoviePilot 识别上下文，但后续真实执行必须逐成员，避免目录批处理重新带回已收口成员。
            work_item = copy.copy(item)
            work_item.members = remaining
            work_item.size = sum(int(_member_size(member) or 0) for member in remaining)
            item = work_item
            rows = {
                source: row
                for source, row in rows.items()
                if source not in existing_handled
            }

    collisions = _collision_groups(plugin, item, rows)
'''
replace_once(old_dispatch, new_dispatch, "batch existing target dispatch")

old_no_collision = '''    if not collisions:
        if not safe:
            return _block_guard_failure(plugin, item, guard_message, details)
        logger.info(
            "【光鸭云盘助手】【数据安全校验】通过: %s，%s 个主视频目标唯一；开始真实整理",
            item.path,
            details.get("expected", len(item.members)),
        )
        return _loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))
'''
new_no_collision = '''    if not collisions:
        if not safe:
            return _block_guard_failure(plugin, item, guard_message, details)
        if existing_handled:
            attempted = failed = 0
            for member in list(getattr(item, "members", None) or []):
                attempted += 1
                success, message = _execute_member(plugin, transfer_chain, kwargs, member, None)
                if not success:
                    failed += 1
                    logger.warning(
                        "【光鸭云盘助手】【整理策略】已有目标成员收口后，剩余成员整理失败: %s - %s",
                        getattr(member, "path", ""),
                        message,
                    )
            return True, (
                f"已有目标策略收口={len(existing_handled)}，剩余成员逐个整理={attempted}，"
                f"调用失败={failed}"
            )
        logger.info(
            "【光鸭云盘助手】【数据安全校验】通过: %s，%s 个主视频目标唯一；开始真实整理",
            item.path,
            details.get("expected", len(item.members)),
        )
        return _loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))
'''
replace_once(old_no_collision, new_no_collision, "mixed batch execution")

PATH.write_text(text, encoding="utf-8")
