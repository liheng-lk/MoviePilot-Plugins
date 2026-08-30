"""v3.6.4：同盘 move 失败事务保护，禁止把不确定移动结果清入回收站并永久删除。

背景：光鸭 ``move_file`` 可能已经真实完成跨目录移动，但后续目标可见性或 rename 确认
仍可能失败。若此时向 MoviePilot 返回失败，宿主的失败清理可能继续调用存储 ``delete``；
当插件又开启 ``permanently_delete`` 时，该文件会先进入回收站，再被延迟彻底删除。

本层只修存储事务边界，不改变 MoviePilot 的媒体识别、分类、命名或目标路径：
1. v3.6.0 ``move_item`` 返回失败后，再检查真实源/目标状态；
2. 目标其实已经按 MoviePilot 目标名可见时，直接按成功收口；
3. 文件已跨目录移动但仅重命名未确认时，再尝试一次强确认 rename；
4. 仍失败且能按源 fileId 唯一定位已移动文件时，优先移动回原目录并确认回滚；
5. 任何仍以失败返回的 move 都登记短期保护记录；MoviePilot 随后的 ``delete``、
   延迟回收站清理和最终永久删除只要命中该记录就被拒绝；
6. 删除包含受保护文件的父目录同样被拒绝，避免目录级失败清理绕过单文件保护；
7. 正常手动删除、已确认重复副本删除等未命中保护记录的操作继续走原逻辑。

原则是：整理失败可以重试，但失败本身绝不能成为不可逆删除的依据。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app import schemas
from app.log import logger

from .guangya_api_v112 import GuangYaApi
from .guangya_rename_integrity_v3414 import _confirmed_named_item


_PROTECT_SECONDS = 15 * 60
_EXTENDED_CONFIRM_TRIES = 60
_EXTENDED_CONFIRM_INTERVAL = 0.5
_ROLLBACK_CONFIRM_TRIES = 40
_ROLLBACK_CONFIRM_INTERVAL = 0.5


def _norm(api: GuangYaApi, value: Any) -> str:
    try:
        return api._normalize_path(str(value or ""))
    except Exception:
        return str(value or "").replace("\\", "/").rstrip("/") or "/"


def _item_size(item: Any) -> Optional[int]:
    try:
        value = getattr(item, "size", None)
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _size_matches(expected: Any, actual: Any) -> bool:
    expected_size = _item_size(expected)
    actual_size = _item_size(actual)
    if expected_size in (None, 0) or actual_size in (None, 0):
        return True
    return expected_size == actual_size


def _same_type(expected: Any, actual: Any) -> bool:
    expected_type = str(getattr(expected, "type", "") or "")
    actual_type = str(getattr(actual, "type", "") or "")
    return not expected_type or not actual_type or expected_type == actual_type


def _find_named_matching(
    api: GuangYaApi,
    *,
    parent_path: str,
    name: str,
    source_item: schemas.FileItem,
) -> Optional[schemas.FileItem]:
    if not name:
        return None
    try:
        item = api._find_item_in_parent(
            parent_path=_norm(api, parent_path),
            name=str(name),
            expected_type=getattr(source_item, "type", None),
        )
    except Exception as err:  # noqa: BLE001 - remote visibility boundary
        logger.debug(
            "【光鸭云盘助手】【v3.6.4】【移动保护】查询真实文件失败: %s/%s - %s",
            parent_path,
            name,
            err,
        )
        return None
    if item and _size_matches(source_item, item) and _same_type(source_item, item):
        return item
    return None


def _target_candidate(
    api: GuangYaApi,
    *,
    source_item: schemas.FileItem,
    target_parent: str,
    target_name: str,
) -> Optional[schemas.FileItem]:
    """回滚候选必须强身份确认；有源 fileId 时绝不降级成同名/同大小猜测。"""
    normalized_target = _norm(api, target_parent)
    source_id = str(getattr(source_item, "fileid", "") or "")

    try:
        target_id = api._path_to_id(normalized_target)
        children = api._iter_parent_items(parent_id=target_id, parent_path=normalized_target)
    except Exception:
        children = []

    if source_id:
        matches = [
            item
            for item in children
            if str(getattr(item, "fileid", "") or "") == source_id
            and _same_type(source_item, item)
            and _size_matches(source_item, item)
        ]
        # 有源 fileId 却无法精确命中时宁可冻结，不允许拿同名文件冒险回滚。
        return matches[0] if len(matches) == 1 else None

    # 只有源端本来就没有 fileId 时，才允许按名字找唯一候选；仍要求类型/大小一致。
    source_name = str(getattr(source_item, "name", "") or Path(str(source_item.path or "")).name)
    candidates = []
    seen = set()
    for name in (target_name, source_name):
        if not name or name in seen:
            continue
        seen.add(name)
        item = _find_named_matching(
            api,
            parent_path=normalized_target,
            name=name,
            source_item=source_item,
        )
        if item:
            candidates.append(item)
    unique = {
        str(getattr(item, "fileid", "") or _norm(api, getattr(item, "path", ""))): item
        for item in candidates
    }
    return next(iter(unique.values())) if len(unique) == 1 else None


def _protection_state(api: GuangYaApi) -> Tuple[threading.RLock, Dict[str, Dict[str, Any]]]:
    lock = getattr(api, "_v364_move_protection_lock", None)
    if lock is None:
        lock = threading.RLock()
        setattr(api, "_v364_move_protection_lock", lock)
    records = getattr(api, "_v364_move_protection", None)
    if not isinstance(records, dict):
        records = {}
        setattr(api, "_v364_move_protection", records)
    return lock, records


def _record_key(source_path: str, target_path: str, fileid: str) -> str:
    return f"{source_path}|{target_path}|{fileid}"


def _protect_failed_move(
    api: GuangYaApi,
    *,
    source_item: schemas.FileItem,
    target_parent: str,
    target_name: str,
    reason: str,
    actual_item: Optional[schemas.FileItem] = None,
) -> Dict[str, Any]:
    source_path = _norm(api, getattr(source_item, "path", ""))
    source_parent = _norm(api, str(Path(source_path).parent))
    source_name = str(getattr(source_item, "name", "") or Path(source_path).name)
    target_parent = _norm(api, target_parent)
    target_name = str(target_name or source_name)
    target_path = _norm(api, str(Path(target_parent) / target_name))

    ids = {
        str(value)
        for value in (
            getattr(source_item, "fileid", ""),
            getattr(actual_item, "fileid", "") if actual_item else "",
        )
        if str(value or "")
    }
    paths = {source_path, target_path}
    names = {source_name, target_name}
    parents = {source_parent, target_parent}
    if actual_item:
        actual_path = _norm(api, getattr(actual_item, "path", ""))
        if actual_path:
            paths.add(actual_path)
            parents.add(_norm(api, str(Path(actual_path).parent)))
        actual_name = str(getattr(actual_item, "name", "") or "")
        if actual_name:
            names.add(actual_name)

    now = time.time()
    record = {
        "source_path": source_path,
        "target_path": target_path,
        "ids": ids,
        "paths": paths,
        "parents": parents,
        "names": names,
        "size": _item_size(source_item),
        "reason": str(reason or "move_failed_uncertain"),
        "created_at": now,
        "expires_at": now + _PROTECT_SECONDS,
    }
    key = _record_key(source_path, target_path, next(iter(ids), ""))
    lock, records = _protection_state(api)
    with lock:
        records[key] = record

    logger.error(
        "【光鸭云盘助手】【v3.6.4】【数据保护】移动失败项已进入删除保护区 %ss：%s -> %s；原因=%s",
        _PROTECT_SECONDS,
        source_path,
        target_path,
        record["reason"],
    )
    return record


def _prune_protection(api: GuangYaApi) -> None:
    lock, records = _protection_state(api)
    now = time.time()
    with lock:
        for key, record in list(records.items()):
            if float(record.get("expires_at") or 0) <= now:
                records.pop(key, None)


def _clear_protection_for_move(
    api: GuangYaApi,
    *,
    source_item: schemas.FileItem,
    target_parent: str,
    target_name: str,
) -> None:
    _prune_protection(api)
    source_path = _norm(api, getattr(source_item, "path", ""))
    source_id = str(getattr(source_item, "fileid", "") or "")
    target_path = _norm(api, str(Path(_norm(api, target_parent)) / str(target_name or source_item.name or "")))
    lock, records = _protection_state(api)
    with lock:
        for key, record in list(records.items()):
            ids = {str(value) for value in (record.get("ids") or set())}
            paths = {_norm(api, value) for value in (record.get("paths") or set())}
            if (source_id and source_id in ids) or source_path in paths or target_path in paths:
                records.pop(key, None)


def _protected_delete_record(api: GuangYaApi, fileitem: schemas.FileItem) -> Optional[Dict[str, Any]]:
    _prune_protection(api)
    path = _norm(api, getattr(fileitem, "path", ""))
    parent = _norm(api, str(Path(path).parent))
    name = str(getattr(fileitem, "name", "") or Path(path).name)
    fileid = str(getattr(fileitem, "fileid", "") or "")
    size = _item_size(fileitem)
    is_dir = str(getattr(fileitem, "type", "") or "") == "dir"
    dir_prefix = f"{path.rstrip('/')}/" if path != "/" else "/"

    lock, records = _protection_state(api)
    with lock:
        for record in records.values():
            ids = {str(value) for value in (record.get("ids") or set())}
            paths = {_norm(api, value) for value in (record.get("paths") or set())}
            parents = {_norm(api, value) for value in (record.get("parents") or set())}
            names = {str(value) for value in (record.get("names") or set())}
            expected_size = record.get("size")

            if fileid and fileid in ids:
                return dict(record)
            if path and path in paths:
                return dict(record)
            # 如果宿主失败清理尝试删整个源/目标父目录，也不能让受保护文件随目录进入回收站。
            if is_dir and any(
                protected_path == path or protected_path.startswith(dir_prefix)
                for protected_path in paths
            ):
                return dict(record)
            if parent in parents and name in names:
                if expected_size in (None, 0) or size in (None, 0) or int(expected_size) == int(size):
                    return dict(record)
    return None


def _rollback_to_source(
    api: GuangYaApi,
    *,
    source_item: schemas.FileItem,
    moved_item: schemas.FileItem,
) -> Tuple[bool, Optional[schemas.FileItem], str]:
    source_path = _norm(api, getattr(source_item, "path", ""))
    source_parent = _norm(api, str(Path(source_path).parent))
    source_name = str(getattr(source_item, "name", "") or Path(source_path).name)

    try:
        source_parent_id = api._path_to_id(source_parent)
    except Exception:
        source_parent_id = str(getattr(source_item, "parent_fileid", "") or "")
    if source_parent != "/" and not source_parent_id:
        return False, moved_item, "原目录 fileId 无法确认"

    moved_id = str(getattr(moved_item, "fileid", "") or "")
    if not moved_id:
        return False, moved_item, "待回滚文件缺少 fileId，拒绝猜测回滚"

    response = api.client.move_file([moved_id], source_parent_id)
    if response.get("msg") != "success" and response.get("code") != 0:
        return False, moved_item, f"回滚 move_file 失败: {response}"

    task_id = (response.get("data", {}) or {}).get("taskId", "")
    if task_id and not api._wait_task_done(task_id, allow_missing=True):
        return False, moved_item, "回滚任务未确认完成"

    moved_path = _norm(api, getattr(moved_item, "path", ""))
    api._invalidate_path_cache(moved_path)
    api._invalidate_path_cache(source_path)
    restored = api._wait_item_visible(
        parent_path=source_parent,
        name=str(getattr(moved_item, "name", "") or source_name),
        expected_type=getattr(source_item, "type", None),
        max_try=_ROLLBACK_CONFIRM_TRIES,
        interval=_ROLLBACK_CONFIRM_INTERVAL,
    )
    if not restored or not _size_matches(source_item, restored):
        return False, restored or moved_item, "已发起回滚，但原目录可见性未确认"

    if str(getattr(restored, "name", "") or "") != source_name:
        if not api.rename(restored, source_name):
            return False, restored, "文件已回原目录，但原文件名恢复未确认"
        restored = _confirmed_named_item(
            api,
            parent_path=source_parent,
            target_name=source_name,
            source_item=source_item,
            compare_fileid=False,
            max_try=_ROLLBACK_CONFIRM_TRIES,
            interval=_ROLLBACK_CONFIRM_INTERVAL,
        )
        if not restored:
            return False, None, "文件已回原目录，但最终原文件名不可见"

    logger.warning(
        "【光鸭云盘助手】【v3.6.4】【移动回滚】MoviePilot 本轮移动无法可靠完成，已把文件安全恢复到原目录: %s",
        source_path,
    )
    return True, restored, "rollback_restored"


def install_move_transaction_guard_v364() -> None:
    """必须在 v3.6.0 move_item 补丁之后安装。"""
    if getattr(GuangYaApi, "_guangya_move_transaction_guard_v364", False):
        return

    previous_move_item = GuangYaApi.move_item
    previous_delete = GuangYaApi.delete
    previous_schedule_purge = GuangYaApi._schedule_purge_from_recycle
    previous_purge = GuangYaApi._purge_from_recycle

    def move_item(
        self: GuangYaApi,
        fileitem: schemas.FileItem,
        path: Path,
        new_name: str,
    ) -> Optional[schemas.FileItem]:
        target_parent = _norm(self, str(path))
        source_path = _norm(self, getattr(fileitem, "path", ""))
        source_parent = _norm(self, str(Path(source_path).parent))
        source_name = str(getattr(fileitem, "name", "") or Path(source_path).name)
        target_name = str(new_name or source_name)

        result = previous_move_item(self, fileitem, path, target_name)
        if result:
            _clear_protection_for_move(
                self,
                source_item=fileitem,
                target_parent=target_parent,
                target_name=target_name,
            )
            return result

        # v3.6.0 已返回失败，但先不要让 MoviePilot 进入失败清理。目标可能只是最终可见性延迟。
        exact_target = _confirmed_named_item(
            self,
            parent_path=target_parent,
            target_name=target_name,
            source_item=fileitem,
            compare_fileid=False,
            max_try=_EXTENDED_CONFIRM_TRIES,
            interval=_EXTENDED_CONFIRM_INTERVAL,
        )
        if exact_target:
            logger.warning(
                "【光鸭云盘助手】【v3.6.4】【移动自愈】前序返回失败，但 MoviePilot 目标文件随后已真实可见，按成功收口: %s",
                _norm(self, getattr(exact_target, "path", "")),
            )
            _clear_protection_for_move(
                self,
                source_item=fileitem,
                target_parent=target_parent,
                target_name=target_name,
            )
            return exact_target

        source_actual = _find_named_matching(
            self,
            parent_path=source_parent,
            name=source_name,
            source_item=fileitem,
        )
        target_actual = _target_candidate(
            self,
            source_item=fileitem,
            target_parent=target_parent,
            target_name=target_name,
        )

        # 已跨目录移动且能强身份确认目标文件时，再尝试一次强确认 rename。
        if target_actual and target_parent != source_parent:
            actual_name = str(getattr(target_actual, "name", "") or "")
            if actual_name != target_name and target_name:
                if self.rename(target_actual, target_name):
                    exact_target = _confirmed_named_item(
                        self,
                        parent_path=target_parent,
                        target_name=target_name,
                        source_item=fileitem,
                        compare_fileid=False,
                        max_try=_EXTENDED_CONFIRM_TRIES,
                        interval=_EXTENDED_CONFIRM_INTERVAL,
                    )
                    if exact_target:
                        logger.warning(
                            "【光鸭云盘助手】【v3.6.4】【移动自愈】跨目录 move 已完成，仅 rename 延迟；重试确认后按成功收口: %s",
                            _norm(self, getattr(exact_target, "path", "")),
                        )
                        _clear_protection_for_move(
                            self,
                            source_item=fileitem,
                            target_parent=target_parent,
                            target_name=target_name,
                        )
                        return exact_target

        # 源已经消失且能按强身份唯一确认目标侧文件，说明远端 move 真实发生；失败前先尝试回滚。
        if not source_actual and target_actual and target_parent != source_parent:
            rollback_ok, rollback_item, rollback_reason = _rollback_to_source(
                self,
                source_item=fileitem,
                moved_item=target_actual,
            )
            _protect_failed_move(
                self,
                source_item=fileitem,
                target_parent=target_parent,
                target_name=target_name,
                reason=rollback_reason,
                actual_item=rollback_item or target_actual,
            )
            if rollback_ok:
                logger.error(
                    "【光鸭云盘助手】【v3.6.4】【数据保护】本轮 move 按失败返回，但源文件已先恢复；后续 MoviePilot 失败清理不得删除该文件: %s",
                    source_path,
                )
            else:
                logger.error(
                    "【光鸭云盘助手】【v3.6.4】【数据保护】远端 move 状态不完整且回滚未确认；已冻结删除，禁止回收站清理: %s",
                    source_path,
                )
            return None

        # 无论源仍在、源/目标同时存在，还是两侧暂时都不可见，只要 move 最终失败，都先保护。
        reason = "move_failed_source_still_present" if source_actual else "move_failed_visibility_uncertain"
        if source_actual and target_actual:
            reason = "move_failed_source_and_target_both_visible"
        _protect_failed_move(
            self,
            source_item=fileitem,
            target_parent=target_parent,
            target_name=target_name,
            reason=reason,
            actual_item=target_actual or source_actual,
        )
        return None

    def delete(self: GuangYaApi, fileitem: schemas.FileItem) -> bool:
        protected = _protected_delete_record(self, fileitem)
        if protected:
            logger.error(
                "【光鸭云盘助手】【v3.6.4】【数据保护】已阻止删除移动失败/状态不确定文件，避免进入回收站: %s；保护原因=%s",
                _norm(self, getattr(fileitem, "path", "")),
                protected.get("reason") or "unknown",
            )
            return False
        return previous_delete(self, fileitem)

    def schedule_purge(self: GuangYaApi, fileitem: schemas.FileItem, *args: Any, **kwargs: Any) -> None:
        protected = _protected_delete_record(self, fileitem)
        if protected:
            logger.error(
                "【光鸭云盘助手】【v3.6.4】【数据保护】已阻止移动失败项加入永久删除队列: %s",
                _norm(self, getattr(fileitem, "path", "")),
            )
            return None
        return previous_schedule_purge(self, fileitem, *args, **kwargs)

    def purge(self: GuangYaApi, fileitem: schemas.FileItem, *args: Any, **kwargs: Any) -> bool:
        protected = _protected_delete_record(self, fileitem)
        if protected:
            logger.error(
                "【光鸭云盘助手】【v3.6.4】【数据保护】永久删除执行前再次命中移动失败保护，拒绝清空回收站项目: %s",
                str(getattr(fileitem, "name", "") or getattr(fileitem, "path", "")),
            )
            return False
        return previous_purge(self, fileitem, *args, **kwargs)

    GuangYaApi.move_item = move_item
    GuangYaApi.delete = delete
    GuangYaApi._schedule_purge_from_recycle = schedule_purge
    GuangYaApi._purge_from_recycle = purge
    GuangYaApi._guangya_move_transaction_guard_v364 = True
    logger.warning(
        "【光鸭云盘助手】【v3.6.4】移动失败事务保护已启用：失败先确认/回滚，未确认文件禁止 delete 与永久回收站清理"
    )


__all__ = [
    "install_move_transaction_guard_v364",
    "_protected_delete_record",
    "_protect_failed_move",
]
