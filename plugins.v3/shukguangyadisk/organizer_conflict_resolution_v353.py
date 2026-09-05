"""v3.5.3：重复目标按媒体身份局部消歧。

原则：
1. MoviePilot 仍负责识别、分类、普通命名、目标目录、覆盖、刮削和整理历史；
2. 只有 MoviePilot 预览已经证明多个主视频将落到同一目标时，本层才介入；
3. 电影：同目标同大小视为重复副本；不同大小保留为稳定的“版本N”；
4. 电视剧：先按 Season/Episode/EpisodeEnd 身份分组，同集可去重/多版本，
   不同集却撞同一目标时只隔离冲突成员，Season 其它安全集继续整理；
5. 重复副本绝不在预览阶段删除，必须等保留文件收到 MoviePilot 成功终态且 history_id
   已落库后，再走光鸭现有 delete -> 回收站 -> 可选延迟彻底删除链；
6. 多版本后缀通过 MoviePilot TransferRename 链式事件写入最终渲染结果，历史记录看到的
   就是真实版本文件名，不做“整理完成后再偷偷改名”。
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.schemas.types import MediaType
from app.sdk.logging import logger

from . import organizer_loss_guard_v349 as _loss_guard
from .organizer_empty_folder_guard_v3410 import (
    _clear_stale_transient_state,
    _live_primary_media_state,
)
from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_policy import FileDisposition, decide_existing_target
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin
from .organizer_recognition import GuangYaOrganizerMixin as GuangYaRecognitionMixin
from .organizer_runtime import organizer_runtime_bound_to


_VERSION_RE = re.compile(r"(?:\s+-\s+版本(?P<num>\d+))$", re.IGNORECASE)
_RENAME_CONTEXT = threading.local()
_PENDING_LOCK = threading.RLock()
_PENDING_DUPLICATES: Dict[str, List[Dict[str, Any]]] = {}


def _norm(plugin: Any, value: Any) -> str:
    try:
        return plugin._organize_normalize_path(str(value or ""))
    except Exception:
        return str(value or "").replace("\\", "/").rstrip("/")


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        return int(match.group(0)) if match else None


def _member_map(plugin: Any, item: _FolderBatchEnvelope) -> Dict[str, Any]:
    return {
        _norm(plugin, getattr(member, "path", "")): member
        for member in list(getattr(item, "members", None) or [])
        if getattr(member, "path", None)
    }


def _member_sort_key(member: Any, path: str) -> Tuple[int, str, str]:
    try:
        size = int(getattr(member, "size", -1))
    except (TypeError, ValueError):
        size = -1
    return (
        size,
        str(getattr(member, "fileid", "") or ""),
        str(path or ""),
    )


def _member_size(member: Any) -> Optional[int]:
    try:
        value = getattr(member, "size", None)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _media_kind(kwargs: Dict[str, Any]) -> str:
    value = kwargs.get("mtype")
    media = kwargs.get("mediainfo")
    if value is None and media is not None:
        value = getattr(media, "type", None)
    if value == MediaType.MOVIE:
        return "movie"
    if value == MediaType.TV:
        return "tv"
    text = str(getattr(value, "value", value) or "").casefold()
    if text in {"电影", "movie", "mediatype.movie"}:
        return "movie"
    if text in {"电视剧", "tv", "mediatype.tv"}:
        return "tv"
    return "unknown"


def _episode_identity(row: Dict[str, Any]) -> Optional[Tuple[int, int, Optional[int]]]:
    season = _to_int(row.get("season"))
    episode = _to_int(row.get("episode"))
    episode_end = _to_int(row.get("episode_end"))
    if season is None or episode is None:
        return None
    return season, episode, episode_end


def _preview_member_rows(
    plugin: Any,
    item: _FolderBatchEnvelope,
    preview: Any,
) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    ok, payload, error = _loss_guard._preview_result(preview)
    if not ok or not isinstance(payload, dict):
        return {}, error or "MoviePilot 预览结果不可用"
    members = _member_map(plugin, item)
    rows: Dict[str, Dict[str, Any]] = {}
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        source = _norm(plugin, raw.get("source"))
        if source in members:
            rows[source] = raw
    return rows, None


def _collision_groups(
    plugin: Any,
    item: _FolderBatchEnvelope,
    rows: Dict[str, Dict[str, Any]],
) -> Dict[str, List[str]]:
    members = _member_map(plugin, item)
    by_target: Dict[str, List[str]] = defaultdict(list)
    for source in members:
        row = rows.get(source)
        if not row or not bool(row.get("success")):
            continue
        target = _norm(plugin, row.get("target"))
        if target:
            by_target[target].append(source)
    return {
        target: sorted(set(sources))
        for target, sources in by_target.items()
        if len(set(sources)) > 1
    }


def _strip_version_stem(stem: str) -> str:
    return _VERSION_RE.sub("", str(stem or "")).rstrip()


def _existing_version_numbers(plugin: Any, target: str) -> Optional[set[int]]:
    """返回已有版本号；网络状态不可靠时返回 None，宁可隔离也不猜。"""
    api = getattr(plugin, "_guangya_api", None)
    if not api:
        return None
    target_path = PurePosixPath(str(target))
    parent_path = target_path.parent.as_posix()
    base_stem = _strip_version_stem(target_path.stem)
    suffix = target_path.suffix.casefold()
    try:
        parent = api.get_item(Path(parent_path))
        if not parent:
            # 目标目录尚未创建，必然没有历史版本文件。
            return set()
        children = api.list(parent) or []
    except Exception as err:  # noqa: BLE001
        logger.warning(
            "【光鸭云盘助手】【多版本消歧】读取目标目录现有版本失败，保持安全隔离: %s - %s",
            parent_path,
            err,
        )
        return None

    numbers: set[int] = set()
    pattern = re.compile(rf"^{re.escape(base_stem)}\s+-\s+版本(?P<num>\d+)$", re.IGNORECASE)
    for child in children:
        if str(getattr(child, "type", "") or "") != "file":
            continue
        name = str(getattr(child, "name", "") or "")
        path = PurePosixPath(name)
        if path.suffix.casefold() != suffix:
            continue
        match = pattern.match(path.stem)
        if match:
            numbers.add(int(match.group("num")))
    return numbers


def _next_version_numbers(plugin: Any, target: str, count: int) -> Optional[List[int]]:
    existing = _existing_version_numbers(plugin, target)
    if existing is None:
        return None
    result: List[int] = []
    number = 1
    while len(result) < count:
        if number not in existing:
            result.append(number)
            existing.add(number)
        number += 1
    return result


def _group_unique_representatives(
    members: Dict[str, Any], sources: Sequence[str]
) -> Tuple[List[str], Dict[str, List[str]]]:
    """同一冲突身份内按字节大小去重；未知大小永远不自动删除。"""
    ordered = sorted(sources, key=lambda source: _member_sort_key(members[source], source))
    size_groups: Dict[int, List[str]] = defaultdict(list)
    unique_unknown: List[str] = []
    for source in ordered:
        size = _member_size(members[source])
        if size is None:
            unique_unknown.append(source)
        else:
            size_groups[size].append(source)

    representatives: List[str] = []
    duplicates: Dict[str, List[str]] = {}
    for size in sorted(size_groups):
        group = sorted(size_groups[size], key=lambda source: _member_sort_key(members[source], source))
        keeper = group[0]
        representatives.append(keeper)
        if len(group) > 1:
            duplicates[keeper] = group[1:]
    representatives.extend(unique_unknown)
    representatives.sort(key=lambda source: _member_sort_key(members[source], source))
    return representatives, duplicates


def _build_conflict_plan(
    plugin: Any,
    item: _FolderBatchEnvelope,
    kwargs: Dict[str, Any],
    rows: Dict[str, Dict[str, Any]],
    collisions: Dict[str, List[str]],
) -> Dict[str, Any]:
    members = _member_map(plugin, item)
    kind = _media_kind(kwargs)
    isolated: Dict[str, str] = {}
    duplicate_of: Dict[str, List[str]] = {}
    versions: Dict[str, int] = {}

    for target, sources in sorted(collisions.items()):
        if kind == "tv":
            identities = [_episode_identity(rows.get(source) or {}) for source in sources]
            if any(identity is None for identity in identities) or len(set(identities)) != 1:
                identity_text = ", ".join(
                    f"{PurePosixPath(source).name}=S{identity[0]:02d}E{identity[1]:02d}"
                    + (f"-E{identity[2]:02d}" if identity and identity[2] is not None else "")
                    if identity else f"{PurePosixPath(source).name}=未知集号"
                    for source, identity in zip(sources, identities)
                )
                for source in sources:
                    isolated[source] = (
                        "不同/未知剧集身份被 MoviePilot 规划到同一目标，仅隔离本冲突组；"
                        f"{identity_text} -> {target}"
                    )
                continue
        elif kind != "movie":
            for source in sources:
                isolated[source] = f"媒体类型未可靠确认但发生重复目标，安全隔离: {target}"
            continue

        representatives, duplicates = _group_unique_representatives(members, sources)
        for keeper, drops in duplicates.items():
            duplicate_of.setdefault(keeper, []).extend(drops)

        # 只有仍存在两个及以上不同大小/未知大小的代表时，才需要版本号。
        if len(representatives) > 1:
            numbers = _next_version_numbers(plugin, target, len(representatives))
            if not numbers:
                for source in sources:
                    isolated[source] = f"无法可靠检查目标目录已有版本号，安全隔离冲突组: {target}"
                duplicate_of = {
                    keeper: [drop for drop in drops if drop not in isolated]
                    for keeper, drops in duplicate_of.items()
                    if keeper not in isolated
                }
                continue
            for source, number in zip(representatives, numbers):
                versions[source] = number

    # 被隔离的成员不能同时进入重复删除关系。
    cleaned_duplicates: Dict[str, List[str]] = {}
    for keeper, drops in duplicate_of.items():
        if keeper in isolated:
            continue
        kept = [source for source in drops if source not in isolated]
        if kept:
            cleaned_duplicates[keeper] = kept

    return {
        "kind": kind,
        "isolated": isolated,
        "duplicates": cleaned_duplicates,
        "versions": versions,
    }


def _mark_blocked(plugin: Any, member: Any, reason: str, *, result: str) -> None:
    path = _norm(plugin, getattr(member, "path", ""))
    if not path:
        return
    fp = plugin._fingerprint(member)
    plugin._state().mark_blocked(
        path=path,
        fingerprint=fp,
        reason=reason,
        now=time.time(),
    )
    plugin._append_monitor_history({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "path": path,
        "name": str(getattr(member, "name", "") or PurePosixPath(path).name),
        "size": int(getattr(member, "size", 0) or 0),
        "result": result,
        "message": reason,
    })


def _register_duplicate_waiters(
    plugin: Any,
    item: _FolderBatchEnvelope,
    duplicates: Dict[str, List[str]],
) -> None:
    members = _member_map(plugin, item)
    with _PENDING_LOCK:
        for keeper, drops in duplicates.items():
            records: List[Dict[str, Any]] = []
            for source in drops:
                member = members[source]
                reason = (
                    f"与保留副本 {PurePosixPath(keeper).name} 同目标且字节大小完全一致；"
                    "等待保留副本真实入库并取得 MoviePilot history_id 后再删除"
                )
                _mark_blocked(plugin, member, reason, result="duplicate_waiting_keeper")
                records.append({
                    "path": source,
                    "name": str(getattr(member, "name", "") or PurePosixPath(source).name),
                    "size": _member_size(member),
                    "fileid": str(getattr(member, "fileid", "") or ""),
                    "fingerprint": plugin._fingerprint(member),
                    "group_path": item.path,
                })
            if records:
                _PENDING_DUPLICATES[_norm(plugin, keeper)] = records
                logger.info(
                    "【光鸭云盘助手】【重复资源】保留=%s；真实入库成功后再删除重复副本=%s",
                    PurePosixPath(keeper).name,
                    ", ".join(record["name"] for record in records),
                )


@contextmanager
def _version_context(plugin: Any, source: str, version: Optional[int]):
    previous = getattr(_RENAME_CONTEXT, "value", None)
    if version is None:
        _RENAME_CONTEXT.value = None
    else:
        _RENAME_CONTEXT.value = {
            "plugin_id": id(plugin),
            "source": _norm(plugin, source),
            "version": int(version),
        }
    try:
        yield
    finally:
        _RENAME_CONTEXT.value = previous


def _apply_version_to_render(render_str: str, version: int) -> str:
    rendered = PurePosixPath(str(render_str or "").replace("\\", "/"))
    stem = _strip_version_stem(rendered.stem)
    name = f"{stem} - 版本{int(version)}{rendered.suffix}"
    if rendered.parent.as_posix() in {"", "."}:
        return name
    return (rendered.parent / name).as_posix()


def _install_rename_handler() -> None:
    if getattr(GuangYaRecognitionMixin, "_guangya_conflict_rename_v353", False):
        return

    def organizer_transfer_rename(self: Any, event: Any) -> None:
        if not organizer_runtime_bound_to(self):
            return
        context = getattr(_RENAME_CONTEXT, "value", None)
        if not isinstance(context, dict) or context.get("plugin_id") != id(self):
            return
        data = getattr(event, "event_data", None)
        source_item = getattr(data, "source_item", None) if data is not None else None
        if not source_item:
            return
        storage = str(getattr(source_item, "storage", "") or "")
        valid_storages = {str(getattr(self, "_disk_name", "") or "")}
        names_getter = getattr(self, "_storage_names", None)
        if callable(names_getter):
            try:
                valid_storages.update(str(value) for value in (names_getter() or set()))
            except Exception:
                pass
        if storage not in valid_storages:
            return

        source = _norm(self, getattr(source_item, "path", "") or getattr(data, "source_path", ""))
        primary = str(context.get("source") or "")
        # 同一次单主视频同步整理中的字幕/音轨也必须带相同版本号，避免伴随文件重新撞名。
        if source != primary:
            if PurePosixPath(source).parent != PurePosixPath(primary).parent:
                return
        render_str = str(getattr(data, "render_str", "") or "")
        if not render_str:
            return
        updated = _apply_version_to_render(render_str, int(context["version"]))
        data.updated = True
        data.updated_str = updated
        data.source = "光鸭云盘助手-v3.5.3"

    GuangYaRecognitionMixin.organizer_transfer_rename = organizer_transfer_rename
    GuangYaRecognitionMixin._guangya_conflict_rename_v353 = True


def _single_preview_target(
    plugin: Any,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    member: Any,
    version: int,
) -> Tuple[Optional[str], str]:
    kwargs = dict(base_kwargs)
    kwargs["fileitem"] = member
    kwargs["preview"] = True
    source = _norm(plugin, getattr(member, "path", ""))
    try:
        with _version_context(plugin, source, version):
            result = transfer_chain.do_transfer(**kwargs)
    except Exception as err:  # noqa: BLE001
        return None, f"版本化预览异常：{err}"
    ok, payload, error = _loss_guard._preview_result(result)
    if not ok or not isinstance(payload, dict):
        return None, error or "版本化预览失败"
    for row in payload.get("items") or []:
        if not isinstance(row, dict):
            continue
        if _norm(plugin, row.get("source")) != source:
            continue
        if not bool(row.get("success")) or not row.get("target"):
            return None, str(row.get("message") or "版本化预览没有有效目标")
        return _norm(plugin, row.get("target")), ""
    return None, "版本化预览没有返回当前主视频"


def _execute_member(
    plugin: Any,
    transfer_chain: Any,
    base_kwargs: Dict[str, Any],
    member: Any,
    version: Optional[int],
) -> Tuple[bool, str]:
    kwargs = dict(base_kwargs)
    kwargs["fileitem"] = member
    kwargs.pop("preview", None)
    source = _norm(plugin, getattr(member, "path", ""))
    try:
        with _version_context(plugin, source, version):
            return _loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))
    except Exception as err:  # noqa: BLE001
        logger.exception("【光鸭云盘助手】【冲突消歧】单成员真实整理异常: %s - %s", source, err)
        return False, str(err)



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


def _block_guard_failure(
    plugin: Any,
    item: _FolderBatchEnvelope,
    message: str,
    details: Dict[str, Any],
) -> Tuple[bool, str]:
    plugin._append_monitor_history({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "path": item.path,
        "name": item.name,
        "size": item.size,
        "result": "folder_safety_blocked",
        "group_path": item.path,
        "group_name": item.name,
        "batch_id": item.batch_id,
        "message": message,
        "safety_details": details,
    })
    logger.error(
        "【光鸭云盘助手】【数据安全校验】已阻止真实整理，源文件保持原位: %s - %s",
        item.path,
        message,
    )
    return False, f"数据安全校验未通过：{message}"


def _execute_conflict_aware(plugin: Any, item: _FolderBatchEnvelope) -> Tuple[bool, str]:
    # 先保留 v3.4.10 的真实源目录门禁，避免陈旧内存任务重新识别。
    live_state, media_count, live_detail = _live_primary_media_state(plugin, item.path)
    if live_state in {"empty", "missing"}:
        removed = _clear_stale_transient_state(plugin, item)
        setattr(item, "_guangya_empty_folder_skip_v3410", True)
        logger.info(
            "【光鸭云盘助手】【空目录保护】跳过陈旧文件夹任务: %s；%s；清理临时状态=%s",
            item.path,
            live_detail,
            removed,
        )
        return True, live_detail
    if live_state == "network":
        return False, live_detail
    if live_state == "media":
        logger.debug("【光鸭云盘助手】【空目录保护】冲突预检前确认源目录仍有视频>=%s: %s", media_count, item.path)

    transfer_chain, directory_item, kwargs, plan_error = _loss_guard._build_moviepilot_kwargs(plugin, item)
    if plan_error:
        return False, plan_error

    preview_kwargs = dict(kwargs)
    preview_kwargs["preview"] = True
    logger.info(
        "【光鸭云盘助手】【数据安全校验】整理前预览: %s，待核对主视频=%s",
        item.path,
        len(item.members),
    )
    try:
        preview = transfer_chain.do_transfer(**preview_kwargs)
    except Exception as err:  # noqa: BLE001
        return False, f"MoviePilot 整理预览异常：{err}"

    safe, guard_message, details = _loss_guard._audit_preview(plugin, item, preview)
    rows, row_error = _preview_member_rows(plugin, item, preview)
    if row_error:
        return _block_guard_failure(plugin, item, row_error, details)

    # v3.7 补齐旧 v3.5.3 只处理“同批多个源撞目标”的缺口：单个新文件如果 MoviePilot
    # 最终目标已经存在，也必须先按统一大小策略决定去重或多版本，禁止直接交给 overwrite。
    if safe and len(list(getattr(item, "members", None) or [])) == 1:
        handled = _handle_single_existing_target(plugin, item, transfer_chain, kwargs, rows)
        if handled is not None:
            return handled

    collisions = _collision_groups(plugin, item, rows)
    # 不是重复目标问题时完全保持 v3.4.9 语义；其它预览异常仍整组阻止。
    if not collisions:
        if not safe:
            return _block_guard_failure(plugin, item, guard_message, details)
        logger.info(
            "【光鸭云盘助手】【数据安全校验】通过: %s，%s 个主视频目标唯一；开始真实整理",
            item.path,
            details.get("expected", len(item.members)),
        )
        return _loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))

    # 如果除了 duplicate_targets 之外还有缺失/失败/空目标，不能拿冲突解析器掩盖其它错误。
    if details.get("missing") or details.get("failed") or details.get("empty_target"):
        return _block_guard_failure(plugin, item, guard_message, details)

    plan = _build_conflict_plan(plugin, item, kwargs, rows, collisions)
    members = _member_map(plugin, item)
    isolated: Dict[str, str] = dict(plan["isolated"])
    duplicates: Dict[str, List[str]] = dict(plan["duplicates"])
    versions: Dict[str, int] = dict(plan["versions"])

    for source, reason in isolated.items():
        member = members.get(source)
        if member:
            _mark_blocked(plugin, member, reason, result="episode_conflict_isolated")
    if isolated:
        logger.warning(
            "【光鸭云盘助手】【剧集冲突隔离】仅隔离冲突成员=%s；当前 Season 其它安全集继续整理: %s",
            len(isolated),
            item.path,
        )

    _register_duplicate_waiters(plugin, item, duplicates)
    duplicate_sources = {source for drops in duplicates.values() for source in drops}

    # 版本化成员必须先用同一个 TransferRename 事件再预览一次，确认后缀真正进入 MP 最终目标。
    valid_version_targets: set[str] = set()
    for source, version in list(versions.items()):
        if source in isolated or source in duplicate_sources:
            versions.pop(source, None)
            continue
        member = members[source]
        target, error = _single_preview_target(plugin, transfer_chain, kwargs, member, version)
        if not target or target in valid_version_targets or f"版本{version}" not in PurePosixPath(target).stem:
            reason = error or f"版本化目标未形成唯一文件名: version={version}, target={target}"
            _mark_blocked(plugin, member, reason, result="version_target_blocked")
            isolated[source] = reason
            versions.pop(source, None)
            continue
        try:
            existing_item = plugin._guangya_api.get_item(Path(target)) if plugin._guangya_api else None
        except Exception as err:  # noqa: BLE001
            reason = f"无法确认版本化目标是否已存在，安全隔离: {target} - {err}"
            _mark_blocked(plugin, member, reason, result="version_target_blocked")
            isolated[source] = reason
            versions.pop(source, None)
            continue
        if existing_item:
            reason = f"版本化目标已存在，拒绝覆盖: {target}"
            _mark_blocked(plugin, member, reason, result="version_target_blocked")
            isolated[source] = reason
            versions.pop(source, None)
            continue
        valid_version_targets.add(target)
        logger.info(
            "【光鸭云盘助手】【多版本消歧】%s -> 版本%s；MoviePilot 二次预览目标=%s",
            PurePosixPath(source).name,
            version,
            target,
        )

    # 只执行安全代表文件；重复副本和异常冲突组保持原位。
    attempted = 0
    failed = 0
    for source, member in sorted(members.items(), key=lambda pair: _member_sort_key(pair[1], pair[0])):
        if source in isolated or source in duplicate_sources:
            continue
        attempted += 1
        success, message = _execute_member(
            plugin,
            transfer_chain,
            kwargs,
            member,
            versions.get(source),
        )
        if not success:
            failed += 1
            logger.warning(
                "【光鸭云盘助手】【冲突消歧】安全成员整理失败，继续当前 Season 其它成员: %s - %s",
                source,
                message,
            )

    plugin._append_monitor_history({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "path": item.path,
        "name": item.name,
        "size": item.size,
        "result": "conflict_resolved_batch",
        "group_path": item.path,
        "group_name": item.name,
        "batch_id": item.batch_id,
        "message": (
            f"重复目标局部处理：实际尝试={attempted}，调用失败={failed}，"
            f"重复副本待删除={len(duplicate_sources)}，多版本={len(versions)}，冲突隔离={len(isolated)}"
        ),
    })

    # 逐文件终态才是成员成功/失败的唯一真相。这里返回 True 只表示冲突批次已安全跑完，
    # 让 v3.4.9 fallback 对任何“未收到终态”的安全成员继续退回 retry，而不是一集失败拖死整季。
    return True, (
        f"冲突批次安全完成：尝试 {attempted}，失败调用 {failed}，"
        f"重复待删 {len(duplicate_sources)}，隔离 {len(isolated)}"
    )


def _delete_duplicate_worker(plugin: Any, keeper: str, history_id: int, records: List[Dict[str, Any]]) -> None:
    api = getattr(plugin, "_guangya_api", None)
    if not api:
        return
    deleted = 0
    for record in records:
        path = str(record.get("path") or "")
        try:
            current = api.get_item(Path(path))
        except Exception as err:  # noqa: BLE001
            logger.warning("【光鸭云盘助手】【重复资源】删除前重新读取失败，保持源文件: %s - %s", path, err)
            continue
        if not current:
            logger.info("【光鸭云盘助手】【重复资源】重复源已不存在，无需再次删除: %s", path)
            try:
                plugin._state().retire_path(path=path)
            except Exception:
                pass
            continue

        expected_size = record.get("size")
        current_size = _member_size(current)
        expected_fileid = str(record.get("fileid") or "")
        current_fileid = str(getattr(current, "fileid", "") or "")
        if expected_size is None or current_size != expected_size:
            logger.error(
                "【光鸭云盘助手】【重复资源】删除前大小已变化，拒绝删除: %s expected=%s current=%s",
                path,
                expected_size,
                current_size,
            )
            continue
        if expected_fileid and current_fileid and expected_fileid != current_fileid:
            logger.error(
                "【光鸭云盘助手】【重复资源】删除前 fileId 已变化，拒绝删除: %s",
                path,
            )
            continue

        if not api.delete(current):
            logger.error("【光鸭云盘助手】【重复资源】移入回收站失败，源文件保持不变: %s", path)
            continue

        deleted += 1
        try:
            plugin._state().retire_path(path=path)
        except Exception:
            pass
        plugin._append_monitor_history({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": path,
            "name": str(record.get("name") or PurePosixPath(path).name),
            "size": int(expected_size or 0),
            "result": "duplicate_deleted_after_keeper",
            "message": (
                f"保留副本已由 MoviePilot 真实入库(history_id={history_id})；"
                f"重复副本已移入回收站{'并进入延迟彻底删除队列' if getattr(api, '_permanently_delete', False) else ''}"
            ),
            "keeper": keeper,
            "transfer_history_id": int(history_id),
        })
        logger.info(
            "【光鸭云盘助手】【重复资源】保留副本 history_id=%s 已确认，重复副本已安全删除: %s",
            history_id,
            path,
        )

    if deleted:
        status = dict(plugin.get_data(plugin._monitor_status_key) or {})
        plugin._save_monitor_status(
            duplicate_deleted_total=int(status.get("duplicate_deleted_total") or 0) + deleted,
            last_duplicate_keeper=keeper,
            last_duplicate_history_id=int(history_id),
        )


def _install_terminal_duplicate_cleanup() -> None:
    if getattr(GuangYaRecognitionMixin, "_guangya_duplicate_terminal_v353", False):
        return
    original_record = GuangYaRecognitionMixin._record_terminal_transfer

    def record(self: Any, event: Any, success: bool) -> None:
        payload_getter = getattr(self, "_event_payload", None)
        payload = payload_getter(event) if callable(payload_getter) else {}
        fileitem = payload.get("fileitem") if isinstance(payload, dict) else None
        source = _norm(self, getattr(fileitem, "path", "")) if fileitem else ""
        history_id = payload.get("transfer_history_id") if isinstance(payload, dict) else None

        original_record(self, event, success)

        if not source:
            return
        with _PENDING_LOCK:
            records = _PENDING_DUPLICATES.pop(source, [])
        if not records:
            return
        if not success or not history_id:
            logger.warning(
                "【光鸭云盘助手】【重复资源】保留副本未取得成功 history_id，不删除任何重复源: %s",
                source,
            )
            return

        threading.Thread(
            target=_delete_duplicate_worker,
            args=(self, source, int(history_id), records),
            name=f"guangya-duplicate-cleanup-{int(time.time())}",
            daemon=True,
        ).start()

    GuangYaRecognitionMixin._record_terminal_transfer = record
    GuangYaRecognitionMixin._guangya_duplicate_terminal_v353 = True


def install_conflict_resolution_v353() -> None:
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_conflict_resolution_v353", False):
        return

    previous_execute = GuangYaQueueRecoveryMixin._execute_isolated_transfer

    def execute(self: Any, item: Any):
        if not isinstance(item, _FolderBatchEnvelope):
            return previous_execute(self, item)
        # v3.7 起单主视频也进入同一 policy：它可能与媒体库已有最终目标发生冲突。
        return _execute_conflict_aware(self, item)

    _install_rename_handler()
    _install_terminal_duplicate_cleanup()
    GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute
    GuangYaQueueRecoveryMixin._guangya_conflict_resolution_v353 = True
    logger.info("【光鸭云盘助手】【v3.5.3】电影重复目标与剧集局部冲突消歧已启用")


__all__ = [
    "install_conflict_resolution_v353",
    "_apply_version_to_render",
    "_episode_identity",
    "_group_unique_representatives",
]
