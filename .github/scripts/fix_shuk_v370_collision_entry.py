from pathlib import Path

path = Path('plugins.v3/shukguangyadisk/organizer_conflict_resolution_v353.py')
text = path.read_text(encoding='utf-8')

old = '''    # v3.7 先把“媒体库已有最终目标”作为比批内碰撞更高优先级的事实处理。\n    # 这样 Season 批次里的每一集都遵守同一条规则，而不是只有单文件任务才检查目标已存在。\n    existing_handled: set[str] = set()\n    if safe:\n        existing_result = _handle_existing_target_groups(plugin, item, transfer_chain, kwargs, rows)\n'''
new = '''    # v3.7 先把“媒体库已有最终目标”作为比批内碰撞更高优先级的事实处理。\n    # duplicate_targets 只是“多个源规划到同一目标”的冲突事实，本身不能阻止已有目标 policy；\n    # 只有 missing/failed/empty_target 才说明预览成员事实不完整，必须先 fail closed。\n    preview_members_valid = not (\n        details.get("missing")\n        or details.get("failed")\n        or details.get("empty_target")\n    )\n    existing_handled: set[str] = set()\n    if preview_members_valid:\n        existing_result = _handle_existing_target_groups(plugin, item, transfer_chain, kwargs, rows)\n'''
if old not in text:
    raise AssertionError('existing-target dispatch point changed')
text = text.replace(old, new, 1)

old = '''    if not collisions:\n        if not safe:\n            return _block_guard_failure(plugin, item, guard_message, details)\n'''
new = '''    if not collisions:\n        # safe 可能仅因原始 duplicate_targets=False；若这些冲突成员已被已有目标 policy 收口，\n        # 剩余成员仍是完整安全预览，不能再用旧 safe 标志把它们误阻断。\n        if not preview_members_valid:\n            return _block_guard_failure(plugin, item, guard_message, details)\n'''
if old not in text:
    raise AssertionError('no-collision safety point changed')
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
