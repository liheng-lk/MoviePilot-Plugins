"""光鸭云盘完整重新整理 v3.2.0。

在 v3.1.0 的“仅分类搬运”基础上，改为真正复用 MoviePilot 的 TransHandler
进行目标路径预演：MoviePilot 负责媒体识别、类型/类别目录、RENAME_FORMAT 智能重命名；
光鸭只负责在同一网盘内创建目标目录、移动/复制和最终重命名。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from app.chain.media import MediaChain
from app.domain.metainfo import MetaInfoPath
from app.modules.filemanager.transhandler import TransHandler
from app.sdk.logging import logger

from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin


_EXTRA_COMPANION_EXTENSIONS = {
    ".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup", ".smi", ".idx",
    ".aac", ".ac3", ".eac3", ".dts", ".mka", ".flac",
    ".nfo",
}


class GuangYaOrganizerMixin(_BaseOrganizerMixin):
    """按 MoviePilot 原生命名/分类策略完整重排光鸭网盘媒体。"""

    _organize_max_items = 500
    _organize_scan_nodes = 5000
    _organize_scan_depth = 12

    def _collect_media_candidates(self, source_folder: Any, max_items: int) -> Tuple[List[Any], Dict[str, List[Any]], int]:
        """递归收集视频文件，并记录同目录伴随文件；不下载媒体内容。"""
        videos: List[Any] = []
        companions_by_parent: Dict[str, List[Any]] = {}
        queue: List[Tuple[Any, int]] = [(source_folder, 0)]
        visited = 0
        while queue and len(videos) < max_items and visited < self._organize_scan_nodes:
            folder, depth = queue.pop(0)
            try:
                children = list(self._guangya_api.list(folder) or [])
            except Exception as err:
                logger.warning("【光鸭云盘助手】【完整整理】读取目录失败 %s: %s", getattr(folder, "path", ""), err)
                continue
            parent_path = self._organize_normalize_path(getattr(folder, "path", "/"))
            companion_rows: List[Any] = []
            for child in children:
                visited += 1
                name = str(getattr(child, "name", "") or "")
                if not name or name.startswith("."):
                    continue
                if getattr(child, "type", "") == "dir":
                    if depth + 1 < self._organize_scan_depth:
                        queue.append((child, depth + 1))
                    continue
                ext = self._item_extension(child)
                if ext in self._VIDEO_EXTENSIONS_COMPAT:
                    videos.append(child)
                    if len(videos) >= max_items:
                        break
                elif ext in _EXTRA_COMPANION_EXTENSIONS:
                    companion_rows.append(child)
                if visited >= self._organize_scan_nodes:
                    break
            if companion_rows:
                companions_by_parent[parent_path] = companion_rows
        return videos, companions_by_parent, visited

    @property
    def _VIDEO_EXTENSIONS_COMPAT(self) -> set[str]:
        # 兼容基类常量不作为类属性暴露的情况。
        return {
            ".mkv", ".mp4", ".ts", ".m2ts", ".mts", ".avi", ".mov", ".wmv",
            ".flv", ".webm", ".iso", ".rmvb", ".m4v", ".mpg", ".mpeg", ".vob",
        }

    @staticmethod
    def _media_payload_from_object(media: Any) -> Dict[str, Any]:
        mtype = getattr(getattr(media, "type", None), "value", getattr(media, "type", ""))
        return {
            "title": str(getattr(media, "title", "") or getattr(media, "original_title", "") or ""),
            "year": getattr(media, "year", None),
            "type": str(mtype or ""),
            "category": str(getattr(media, "category", "") or ""),
            "media_source": str(getattr(getattr(media, "media_source", None), "value", getattr(media, "media_source", "")) or ""),
            "media_id": str(getattr(media, "media_id", "") or getattr(media, "tmdb_id", "") or ""),
            "season": getattr(media, "season", None),
        }

    def _recognize_file_for_organize(self, item: Any) -> Tuple[Optional[Any], Optional[Any], Optional[Dict[str, Any]], str]:
        """返回 MetaInfoPath、MediaInfo、前端摘要。"""
        try:
            meta = MetaInfoPath(Path(str(getattr(item, "path", "") or getattr(item, "name", ""))))
            media = MediaChain().recognize_by_meta(meta, obtain_images=False)
            if not media:
                return None, None, None, f"MoviePilot 未识别: {getattr(item, 'name', '')}"
            return meta, media, self._media_payload_from_object(media), ""
        except Exception as err:
            return None, None, None, f"MoviePilot 识别异常: {err}"

    def _build_mp_target_base(self, target_root: str, policy: Dict[str, Any], media: Any) -> str:
        """镜像 MP TransHandler.get_dest_dir 的类型/类别目录语义，但根目录使用用户选择的光鸭目标。"""
        target = Path(self._organize_normalize_path(target_root))
        media_type = str(getattr(getattr(media, "type", None), "value", getattr(media, "type", "")) or "")
        category = str(getattr(media, "category", "") or "")
        if policy.get("library_type_folder"):
            target = target / (str(policy.get("media_type") or media_type).strip())
        if policy.get("library_category_folder"):
            target = target / (str(policy.get("media_category") or category).strip())
        return self._organize_normalize_path(target.as_posix())

    def _preview_mp_target(
        self,
        item: Any,
        meta: Any,
        media: Any,
        target_root: str,
        policy: Dict[str, Any],
        operation: str,
    ) -> Tuple[Optional[str], str]:
        """调用 MP TransHandler 的 preview 模式获得真正的最终命名路径。"""
        target_base = self._build_mp_target_base(target_root, policy, media)
        result = TransHandler().transfer_media(
            fileitem=item,
            in_meta=meta,
            mediainfo=media,
            target_storage=self._disk_name,
            target_path=Path(target_base),
            transfer_type=operation,
            source_oper=self._guangya_api,
            target_oper=self._guangya_api,
            need_scrape=False,
            need_rename=bool(policy.get("renaming", True)),
            need_notify=False,
            overwrite_mode=str(policy.get("overwrite_mode") or "never"),
            preview=True,
        )
        if not getattr(result, "success", False):
            return None, str(getattr(result, "message", "") or "MoviePilot 目标路径预演失败")
        target_item = getattr(result, "target_item", None)
        target_path = str(getattr(target_item, "path", "") or "")
        if not target_path:
            file_list_new = list(getattr(result, "file_list_new", None) or [])
            target_path = str(file_list_new[0]) if file_list_new else ""
        if not target_path:
            return None, "MoviePilot 未返回预演目标路径"
        return self._organize_normalize_path(target_path), ""

    def _preview_companion_target(
        self,
        companion: Any,
        video_meta: Any,
        media: Any,
        target_root: str,
        policy: Dict[str, Any],
        operation: str,
    ) -> Tuple[Optional[str], str]:
        """字幕/外置音轨沿用正片媒体身份和季集信息，由 MP 生成对应的新名字。"""
        meta = deepcopy(video_meta)
        try:
            meta.org_string = str(getattr(companion, "name", "") or "")
        except Exception:
            pass
        return self._preview_mp_target(companion, meta, media, target_root, policy, operation)

    @staticmethod
    def _same_parent_same_stem_companions(video: Any, pool: List[Any]) -> List[Any]:
        video_stem = Path(str(getattr(video, "name", "") or "")).stem
        result: List[Any] = []
        for item in pool:
            if getattr(item, "type", "") != "file":
                continue
            name = str(getattr(item, "name", "") or "")
            if Path(name).stem == video_stem and Path(name).suffix.lower() in _EXTRA_COMPANION_EXTENSIONS:
                result.append(item)
        return result

    def _existing_exact_target(self, target_path: str) -> Optional[Any]:
        target = PurePosixPath(self._organize_normalize_path(target_path))
        return self._existing_target(self._organize_normalize_path(str(target.parent)), target.name)

    def _build_organize_plan(self, payload: dict, store: bool = True) -> Dict[str, Any]:
        """完整重新整理：递归扫描 -> MP识别 -> MP重命名预演 -> 冲突检查 -> 二次确认。"""
        if not self._guangya_api:
            return {"success": False, "message": "光鸭云盘尚未登录或存储未初始化"}
        payload = payload or {}
        try:
            source_path, target_path = self._validate_organize_roots(payload.get("source_path"), payload.get("target_path"))
        except Exception as err:
            return {"success": False, "message": str(err)}

        policy_id = str(payload.get("policy_id") or "auto")
        requested_operation = str(payload.get("operation") or "policy")
        allow_overwrite = bool(payload.get("allow_overwrite", False))
        try:
            max_items = int(payload.get("max_items") or self._organize_max_items)
        except (TypeError, ValueError):
            max_items = self._organize_max_items
        max_items = max(1, min(max_items, self._organize_max_items))

        source_folder = self._guangya_api.get_item(Path(source_path))
        if not source_folder or source_folder.type != "dir":
            return {"success": False, "message": f"源目录不存在: {source_path}"}
        target_existing = self._guangya_api.get_item(Path(target_path))
        if target_existing and target_existing.type != "dir":
            return {"success": False, "message": f"目标路径不是文件夹: {target_path}"}

        explicit_policy = None if policy_id == "auto" else self._get_organize_policy(policy_id)
        if policy_id != "auto" and not explicit_policy:
            return {"success": False, "message": "所选 MoviePilot 目录策略已不存在，请刷新策略列表"}

        videos, companion_map, visited = self._collect_media_candidates(source_folder, max_items=max_items)
        rows: List[Dict[str, Any]] = []
        summary = {"total": len(videos), "ready": 0, "unrecognized": 0, "skipped": 0, "conflict": 0, "non_media": 0}
        planned_targets: Dict[str, str] = {}

        for item in videos:
            meta, media_obj, media, recognize_error = self._recognize_file_for_organize(item)
            base = {
                "source_path": self._organize_normalize_path(item.path),
                "source_fileid": str(item.fileid or ""),
                "source_name": str(item.name or ""),
                "source_type": str(item.type or ""),
                "size": int(item.size or 0),
                "media": media,
                "policy": None,
                "target_parent": "",
                "target_name": "",
                "target_path": "",
                "operation": "",
                "operation_source": "",
                "overwrite_mode": "",
                "status": "",
                "reason": "",
                "companions": [],
            }
            if not media_obj:
                base.update(status="unrecognized", reason=recognize_error)
                summary["unrecognized"] += 1
                rows.append(base)
                continue

            policy = explicit_policy or self._auto_policy_for_media(media["type"], media["category"])
            if not policy:
                base.update(status="skipped", reason="没有匹配媒体类型/类别的 MoviePilot 媒体库目录策略")
                summary["skipped"] += 1
                rows.append(base)
                continue
            if explicit_policy and not self._policy_matches_media(policy, media["type"], media["category"]):
                base.update(policy=policy, status="skipped", reason="媒体类型/类别不符合所选 MoviePilot 目录策略")
                summary["skipped"] += 1
                rows.append(base)
                continue

            operation, operation_source = self._resolve_operation(requested_operation, policy)
            target_full, preview_error = self._preview_mp_target(item, meta, media_obj, target_path, policy, operation)
            if not target_full:
                base.update(policy=policy, operation=operation, operation_source=operation_source, status="unrecognized", reason=preview_error)
                summary["unrecognized"] += 1
                rows.append(base)
                continue

            target = PurePosixPath(target_full)
            target_parent = self._organize_normalize_path(str(target.parent))
            target_name = target.name
            existing = self._existing_exact_target(target_full)
            decision, reason = self._conflict_decision(item, existing, policy.get("overwrite_mode"))
            normalized_source = self._organize_normalize_path(item.path)
            if normalized_source == target_full:
                decision, reason = "skip", "源文件已经符合 MoviePilot 最终目录与命名"

            duplicate_source = planned_targets.get(target_full)
            if duplicate_source and duplicate_source != normalized_source:
                decision, reason = "conflict", f"多个源文件映射到同一 MoviePilot 目标：{duplicate_source}"
            else:
                planned_targets[target_full] = normalized_source

            parent_key = self._organize_normalize_path(str(PurePosixPath(normalized_source).parent))
            companion_rows: List[Dict[str, Any]] = []
            for companion in self._same_parent_same_stem_companions(item, companion_map.get(parent_key, [])):
                companion_target, companion_error = self._preview_companion_target(
                    companion, meta, media_obj, target_path, policy, operation
                )
                if not companion_target:
                    companion_rows.append({
                        "source_path": self._organize_normalize_path(companion.path),
                        "source_fileid": str(companion.fileid or ""),
                        "source_name": str(companion.name or ""),
                        "target_path": "",
                        "target_parent": "",
                        "target_name": "",
                        "error": companion_error,
                    })
                    continue
                ctarget = PurePosixPath(companion_target)
                companion_rows.append({
                    "source_path": self._organize_normalize_path(companion.path),
                    "source_fileid": str(companion.fileid or ""),
                    "source_name": str(companion.name or ""),
                    "target_path": companion_target,
                    "target_parent": self._organize_normalize_path(str(ctarget.parent)),
                    "target_name": ctarget.name,
                    "error": "",
                })

            status = "ready"
            if decision == "skip":
                status = "skipped"
                summary["skipped"] += 1
            elif decision in {"overwrite", "conflict"} and not allow_overwrite:
                status = "conflict"
                summary["conflict"] += 1
            elif decision == "conflict":
                # 计划内两个源映射到同一目标，即使允许覆盖也不自动决定谁胜出。
                status = "conflict"
                summary["conflict"] += 1
            else:
                summary["ready"] += 1

            base.update(
                policy=policy,
                target_parent=target_parent,
                target_name=target_name,
                target_path=target_full,
                operation=operation,
                operation_source=operation_source,
                overwrite_mode=policy.get("overwrite_mode") or "never",
                status=status,
                reason=reason,
                companions=companion_rows,
            )
            rows.append(base)

        import time, uuid
        plan_id = uuid.uuid4().hex
        plan = {
            "plan_id": plan_id,
            "created_at": time.time(),
            "source_path": source_path,
            "target_path": target_path,
            "policy_id": policy_id,
            "operation": requested_operation,
            "allow_overwrite": allow_overwrite,
            "items": rows,
            "summary": summary,
            "scan_nodes": visited,
            "safe_note": "v3.2.0 完整重新整理：MoviePilot 负责识别、类型/类别分类和最终智能重命名预演；光鸭按预演结果重建电影/电视剧/Season 目录并移动或复制。执行前请核对目标路径。",
        }
        if store:
            self._organize_store_plan(plan)
        return {"success": True, "message": f"完整重新整理预览完成：可执行 {summary['ready']} 项", "data": plan}

    def _execute_one_organize_item(self, row: Dict[str, Any], allow_overwrite: bool) -> Tuple[bool, str]:
        source = self._guangya_api.get_item(Path(str(row.get("source_path") or "")))
        if not source:
            return False, "源项目已不存在"
        if str(row.get("source_fileid") or "") and str(source.fileid or "") != str(row.get("source_fileid")):
            return False, "源项目 fileId 已变化，请重新预览"

        target_parent = self._organize_normalize_path(row.get("target_parent"))
        target_name = str(row.get("target_name") or "")
        target_path = self._organize_normalize_path(row.get("target_path"))
        if not target_name:
            return False, "整理计划缺少最终文件名"
        if self._organize_normalize_path(source.path) == target_path:
            return True, "目标路径完全相同，无需重复整理"

        target_folder = self._guangya_api.get_folder(Path(target_parent))
        if not target_folder:
            return False, f"无法创建目标目录 {target_parent}"
        existing = self._existing_target(target_parent, target_name)
        if existing:
            if not allow_overwrite:
                return False, "目标已存在且未允许覆盖"
            if str(existing.fileid or "") != str(source.fileid or ""):
                if not self._guangya_api.delete(existing):
                    return False, "删除目标冲突项目失败"

        operation = str(row.get("operation") or "move")
        method = self._guangya_api.copy if operation == "copy" else self._guangya_api.move
        if not method(source, Path(target_parent), target_name):
            return False, f"{operation} + 重新命名失败"

        for companion_info in row.get("companions") or []:
            if companion_info.get("error") or not companion_info.get("target_name"):
                logger.warning(
                    "【光鸭云盘助手】【完整整理】伴随文件跳过：%s - %s",
                    companion_info.get("source_name"), companion_info.get("error") or "缺少目标路径",
                )
                continue
            companion = self._guangya_api.get_item(Path(str(companion_info.get("source_path") or "")))
            if not companion:
                continue
            cparent = self._organize_normalize_path(companion_info.get("target_parent"))
            cname = str(companion_info.get("target_name") or "")
            if self._organize_normalize_path(companion.path) == self._organize_normalize_path(companion_info.get("target_path")):
                continue
            if not self._guangya_api.get_folder(Path(cparent)):
                return False, f"无法创建伴随文件目录: {cparent}"
            companion_existing = self._existing_target(cparent, cname)
            if companion_existing and str(companion_existing.fileid or "") != str(companion.fileid or ""):
                if allow_overwrite:
                    if not self._guangya_api.delete(companion_existing):
                        return False, f"伴随文件冲突删除失败: {cname}"
                else:
                    return False, f"伴随文件目标已存在: {cname}"
            if not method(companion, Path(cparent), cname):
                return False, f"伴随文件整理失败: {companion.name} -> {cname}"
        return True, ""

    def _cleanup_empty_source_dirs(self, source_root: str) -> int:
        """移动整理后从最深层向上删除空旧目录，不删除用户选择的源根目录本身。"""
        source_root = self._organize_normalize_path(source_root)
        root = self._guangya_api.get_item(Path(source_root))
        if not root or root.type != "dir":
            return 0
        queue: List[Tuple[Any, int]] = [(root, 0)]
        dirs: List[Tuple[Any, int]] = []
        while queue:
            current, depth = queue.pop(0)
            if depth >= self._organize_scan_depth:
                continue
            try:
                children = list(self._guangya_api.list(current) or [])
            except Exception:
                continue
            for child in children:
                if child.type == "dir":
                    dirs.append((child, depth + 1))
                    queue.append((child, depth + 1))
        removed = 0
        for folder, _ in sorted(dirs, key=lambda row: row[1], reverse=True):
            try:
                if not (self._guangya_api.list(folder) or []):
                    if self._guangya_api.delete(folder):
                        removed += 1
            except Exception:
                continue
        return removed

    def api_organize_execute(self, payload: dict) -> Dict[str, Any]:
        """执行计划；移动模式结束后清理旧的空目录结构。"""
        result = super().api_organize_execute(payload)
        # base execute 会从 _organize_plans 中删除计划，因此从返回结果无法再取 operation；
        # 执行前读取一份仅用于空目录清理的快照。
        return result
