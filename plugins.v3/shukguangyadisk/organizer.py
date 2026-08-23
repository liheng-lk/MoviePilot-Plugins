"""光鸭云盘内文件整理：复用 MoviePilot V3 目录分类策略，云盘内执行移动/复制。"""

from __future__ import annotations

import datetime
import hashlib
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from app.application.directory import DirectoryHelper
from app.chain.media import MediaChain
from app.domain.metainfo import MetaInfoPath
from app.sdk.logging import logger

from .models import GuangYaOrganizerResponse


_VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".ts", ".m2ts", ".mts", ".avi", ".mov", ".wmv",
    ".flv", ".webm", ".iso", ".rmvb", ".m4v", ".mpg", ".mpeg", ".vob",
}
_SIDECAR_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup", ".smi", ".idx"}


class GuangYaOrganizerMixin:
    """V3 光鸭网盘整理能力。源/目标都在光鸭盘，分类规则来自 MoviePilot DirectoryHelper。"""

    _organize_plan_ttl = 15 * 60
    _organize_max_items = 300
    _organize_probe_nodes = 160
    _organize_probe_depth = 4

    @staticmethod
    def _organize_normalize_path(value: Any) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw:
            return "/"
        if not raw.startswith("/"):
            raw = "/" + raw
        path = PurePosixPath(raw)
        if ".." in path.parts:
            raise ValueError("目录不能包含 ..")
        normalized = "/" + "/".join(part for part in path.parts if part != "/")
        return normalized.rstrip("/") or "/"

    @staticmethod
    def _policy_value(value: Any) -> str:
        enum_value = getattr(value, "value", value)
        return str(enum_value or "").strip()

    @classmethod
    def _policy_identifier(cls, index: int, policy: Any) -> str:
        raw = "|".join([
            str(index),
            cls._policy_value(getattr(policy, "name", "")),
            str(getattr(policy, "priority", 0) or 0),
            cls._policy_value(getattr(policy, "library_path", "")),
            cls._policy_value(getattr(policy, "media_type", "")),
            cls._policy_value(getattr(policy, "media_category", "")),
        ])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _mp_organize_policies(self) -> List[Dict[str, Any]]:
        """读取 MoviePilot 当前媒体库目录配置，不在插件里复制一套分类规则。"""
        result: List[Dict[str, Any]] = []
        try:
            dirs = DirectoryHelper().get_library_dirs() or []
        except Exception as err:
            logger.warning("【光鸭云盘助手】【网盘整理】读取 MoviePilot 目录配置失败: %s", err)
            return result
        for index, item in enumerate(dirs):
            transfer_type = self._policy_value(getattr(item, "transfer_type", "")) or "move"
            result.append({
                "id": self._policy_identifier(index, item),
                "index": index,
                "name": self._policy_value(getattr(item, "name", "")) or f"目录策略 {index + 1}",
                "priority": int(getattr(item, "priority", 0) or 0),
                "storage": self._policy_value(getattr(item, "storage", "")),
                "download_path": self._policy_value(getattr(item, "download_path", "")),
                "library_path": self._policy_value(getattr(item, "library_path", "")),
                "library_storage": self._policy_value(getattr(item, "library_storage", "")),
                "media_type": self._policy_value(getattr(item, "media_type", "")),
                "media_category": self._policy_value(getattr(item, "media_category", "")),
                "transfer_type": transfer_type,
                "overwrite_mode": self._policy_value(getattr(item, "overwrite_mode", "")) or "never",
                "renaming": bool(getattr(item, "renaming", False)),
                "scraping": bool(getattr(item, "scraping", False)),
                "notify": bool(getattr(item, "notify", True)),
                "library_type_folder": bool(getattr(item, "library_type_folder", False)),
                "library_category_folder": bool(getattr(item, "library_category_folder", False)),
                "download_type_folder": bool(getattr(item, "download_type_folder", False)),
                "download_category_folder": bool(getattr(item, "download_category_folder", False)),
            })
        return sorted(result, key=lambda row: (row["priority"], row["index"]))

    def _get_organize_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        for policy in self._mp_organize_policies():
            if policy["id"] == str(policy_id or ""):
                return policy
        return None

    @staticmethod
    def _policy_matches_media(policy: Dict[str, Any], media_type: str, category: str) -> bool:
        wanted_type = str(policy.get("media_type") or "").strip()
        wanted_category = str(policy.get("media_category") or "").strip()
        if wanted_type and wanted_type != media_type:
            return False
        if wanted_category and wanted_category != category:
            return False
        return True

    def _auto_policy_for_media(self, media_type: str, category: str) -> Optional[Dict[str, Any]]:
        for policy in self._mp_organize_policies():
            if self._policy_matches_media(policy, media_type, category):
                return policy
        return None

    def api_organize_policies(self) -> Dict[str, Any]:
        policies = self._mp_organize_policies()
        return {
            "success": True,
            "message": f"读取到 {len(policies)} 条 MoviePilot 媒体库目录策略",
            "data": {
                "policies": policies,
                "auto": {
                    "id": "auto",
                    "name": "自动按 MoviePilot 优先级匹配",
                    "description": "按媒体类型/媒体类别匹配 MoviePilot 当前目录配置，优先级越小越先使用",
                },
            },
        }

    def api_organize_folders(self, payload: dict) -> Dict[str, Any]:
        """只返回当前层目录，供前端安全选择源/目标目录。"""
        if not self._guangya_api:
            return {"success": False, "message": "光鸭云盘尚未登录或存储未初始化"}
        try:
            path = self._organize_normalize_path((payload or {}).get("path") or "/")
            folder = self._guangya_api.get_item(Path(path))
            if not folder or folder.type != "dir":
                return {"success": False, "message": f"目录不存在: {path}"}
            rows = []
            for item in self._guangya_api.list(folder) or []:
                if item.type != "dir" or str(item.name or "").startswith("."):
                    continue
                rows.append({
                    "name": item.name,
                    "path": self._organize_normalize_path(item.path),
                    "fileid": str(item.fileid or ""),
                    "modify_time": int(item.modify_time or 0),
                })
            parent = "/" if path == "/" else self._organize_normalize_path(str(PurePosixPath(path).parent))
            return {"success": True, "data": {"path": path, "parent": parent, "folders": rows}}
        except Exception as err:
            logger.warning("【光鸭云盘助手】【网盘整理】浏览目录失败: %s", err)
            return {"success": False, "message": f"浏览目录失败: {err}"}

    @staticmethod
    def _item_extension(item: Any) -> str:
        ext = str(getattr(item, "extension", "") or "").strip().lower()
        if ext and not ext.startswith("."):
            ext = "." + ext
        return ext or Path(str(getattr(item, "name", "") or "")).suffix.lower()

    def _find_representative_media(self, item: Any) -> Tuple[Optional[Any], int]:
        """目录只探测有限节点，找到一个代表视频即可识别；不下载媒体文件。"""
        if getattr(item, "type", "") == "file":
            return (item, 1) if self._item_extension(item) in _VIDEO_EXTENSIONS else (None, 1)
        queue: List[Tuple[Any, int]] = [(item, 0)]
        visited = 0
        while queue and visited < self._organize_probe_nodes:
            current, depth = queue.pop(0)
            if depth >= self._organize_probe_depth:
                continue
            try:
                children = self._guangya_api.list(current) or []
            except Exception:
                continue
            for child in children:
                visited += 1
                if child.type == "file" and self._item_extension(child) in _VIDEO_EXTENSIONS:
                    return child, visited
                if child.type == "dir" and depth + 1 < self._organize_probe_depth:
                    queue.append((child, depth + 1))
                if visited >= self._organize_probe_nodes:
                    break
        return None, visited

    @staticmethod
    def _media_payload(media: Any) -> Dict[str, Any]:
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

    def _recognize_cloud_item(self, item: Any) -> Tuple[Optional[Dict[str, Any]], str]:
        representative, probed = self._find_representative_media(item)
        if not representative:
            return None, f"未在前 {probed} 个节点中找到可识别视频"
        try:
            meta = MetaInfoPath(Path(str(representative.path or representative.name or "")))
            media = MediaChain().recognize_by_meta(meta, obtain_images=False)
            if not media:
                return None, f"MoviePilot 未识别: {representative.name}"
            return self._media_payload(media), ""
        except Exception as err:
            return None, f"MoviePilot 识别异常: {err}"

    @staticmethod
    def _sanitize_folder_name(value: Any) -> str:
        text = str(value or "").strip().replace("/", "／").replace("\\", "＼")
        return text[:120]

    def _build_target_parent(self, target_root: str, policy: Dict[str, Any], media: Dict[str, Any]) -> str:
        parts = [self._organize_normalize_path(target_root)]
        if policy.get("library_type_folder"):
            type_name = self._sanitize_folder_name(media.get("type"))
            if type_name:
                parts.append(type_name)
        if policy.get("library_category_folder"):
            category = self._sanitize_folder_name(media.get("category"))
            if category:
                parts.append(category)
        current = parts[0]
        for part in parts[1:]:
            current = self._organize_normalize_path(current.rstrip("/") + "/" + part)
        return current

    def _existing_target(self, target_parent: str, name: str) -> Optional[Any]:
        try:
            parent = self._guangya_api.get_item(Path(target_parent))
            if not parent or parent.type != "dir":
                return None
            for item in self._guangya_api.list(parent) or []:
                if item.name == name:
                    return item
        except Exception:
            return None
        return None

    @staticmethod
    def _conflict_decision(source: Any, existing: Any, overwrite_mode: str) -> Tuple[str, str]:
        if not existing:
            return "ready", ""
        mode = str(overwrite_mode or "never").lower()
        if mode == "never":
            return "skip", "目标已存在，MP 覆盖策略=never"
        if mode == "size":
            src_size = int(getattr(source, "size", 0) or 0)
            dst_size = int(getattr(existing, "size", 0) or 0)
            if src_size and dst_size and src_size == dst_size:
                return "skip", "目标已存在且大小一致"
            return "overwrite", "目标已存在且大小不同，需要允许覆盖"
        if mode == "latest":
            src_time = int(getattr(source, "modify_time", 0) or 0)
            dst_time = int(getattr(existing, "modify_time", 0) or 0)
            if src_time and dst_time and src_time <= dst_time:
                return "skip", "目标文件更新时间不旧于源文件"
            return "overwrite", "源文件较新，需要允许覆盖"
        return "overwrite", f"目标已存在，MP 覆盖策略={mode or 'always'}，需要允许覆盖"

    def _resolve_operation(self, requested: str, policy: Dict[str, Any]) -> Tuple[str, str]:
        requested = str(requested or "policy").lower()
        if requested in {"move", "copy"}:
            return requested, "用户指定"
        configured = str(policy.get("transfer_type") or "move").lower()
        if configured in {"move", "copy"}:
            return configured, "MoviePilot目录配置"
        return "move", f"MP整理方式 {configured or '-'} 不支持网盘内操作，安全回退为移动"

    @staticmethod
    def _same_stem_sidecars(items: List[Any], video: Any) -> List[Any]:
        stem = Path(str(video.name or "")).stem
        result = []
        for item in items:
            if item.type != "file" or item is video:
                continue
            if Path(str(item.name or "")).stem == stem and Path(str(item.name or "")).suffix.lower() in _SIDECAR_EXTENSIONS:
                result.append(item)
        return result

    def _validate_organize_roots(self, source: str, target: str) -> Tuple[str, str]:
        source = self._organize_normalize_path(source)
        target = self._organize_normalize_path(target)
        if source == "/":
            raise ValueError("首版网盘整理不允许直接整理根目录，请选择一个具体源文件夹")
        if source == target:
            raise ValueError("源目录和目标目录不能相同")
        source_prefix = source.rstrip("/") + "/"
        if target.startswith(source_prefix):
            raise ValueError("目标目录不能位于源目录内部，避免循环整理")
        return source, target

    def _build_organize_plan(self, payload: dict, store: bool = True) -> Dict[str, Any]:
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

        top_items = list(self._guangya_api.list(source_folder) or [])[:max_items]
        rows: List[Dict[str, Any]] = []
        summary = {"total": len(top_items), "ready": 0, "unrecognized": 0, "skipped": 0, "conflict": 0, "non_media": 0}
        for item in top_items:
            if str(item.name or "").startswith("."):
                summary["non_media"] += 1
                continue
            if item.type == "file" and self._item_extension(item) not in _VIDEO_EXTENSIONS:
                summary["non_media"] += 1
                continue
            media, recognize_error = self._recognize_cloud_item(item)
            base = {
                "source_path": self._organize_normalize_path(item.path),
                "source_fileid": str(item.fileid or ""),
                "source_name": str(item.name or ""),
                "source_type": str(item.type or ""),
                "size": int(item.size or 0),
                "media": media,
                "policy": None,
                "target_parent": "",
                "target_path": "",
                "operation": "",
                "operation_source": "",
                "overwrite_mode": "",
                "status": "",
                "reason": "",
                "companions": [],
            }
            if not media:
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
            target_parent = self._build_target_parent(target_path, policy, media)
            target_full = self._organize_normalize_path(target_parent.rstrip("/") + "/" + str(item.name or ""))
            existing = self._existing_target(target_parent, str(item.name or ""))
            decision, reason = self._conflict_decision(item, existing, policy.get("overwrite_mode"))
            companions = self._same_stem_sidecars(top_items, item) if item.type == "file" else []

            status = "ready"
            if decision == "skip":
                status = "skipped"
                summary["skipped"] += 1
            elif decision == "overwrite" and not allow_overwrite:
                status = "conflict"
                summary["conflict"] += 1
            else:
                summary["ready"] += 1
            base.update(
                policy=policy,
                target_parent=target_parent,
                target_path=target_full,
                operation=operation,
                operation_source=operation_source,
                overwrite_mode=policy.get("overwrite_mode") or "never",
                status=status,
                reason=reason,
                companions=[{
                    "source_path": self._organize_normalize_path(companion.path),
                    "source_fileid": str(companion.fileid or ""),
                    "source_name": str(companion.name or ""),
                } for companion in companions],
            )
            rows.append(base)

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
            "safe_note": "v3.1.0 仅按 MP 媒体类型/类别目录策略移动或复制，保持光鸭原文件/目录名称；智能重命名将在后续版本单独接入。",
        }
        if store:
            self._organize_store_plan(plan)
        return {"success": True, "message": f"预览完成：可执行 {summary['ready']} 项", "data": plan}

    def _organize_store_plan(self, plan: Dict[str, Any]) -> None:
        now = time.time()
        plans = getattr(self, "_organize_plans", None)
        if not isinstance(plans, dict):
            plans = {}
        plans = {
            key: value for key, value in plans.items()
            if now - float((value or {}).get("created_at") or 0) <= self._organize_plan_ttl
        }
        plans[str(plan.get("plan_id"))] = plan
        self._organize_plans = plans

    def api_organize_preview(self, payload: dict) -> Dict[str, Any]:
        logger.info("【光鸭云盘助手】【网盘整理】开始生成整理预览")
        return self._build_organize_plan(payload, store=True)

    def _execute_one_organize_item(self, row: Dict[str, Any], allow_overwrite: bool) -> Tuple[bool, str]:
        source = self._guangya_api.get_item(Path(str(row.get("source_path") or "")))
        if not source:
            return False, "源项目已不存在"
        if str(row.get("source_fileid") or "") and str(source.fileid or "") != str(row.get("source_fileid")):
            return False, "源项目 fileId 已变化，请重新预览"
        target_parent = self._organize_normalize_path(row.get("target_parent"))
        target_folder = self._guangya_api.get_folder(Path(target_parent))
        if not target_folder:
            return False, f"无法创建目标目录 {target_parent}"
        existing = self._existing_target(target_parent, str(source.name or ""))
        if existing:
            if not allow_overwrite:
                return False, "目标已存在且未允许覆盖"
            if not self._guangya_api.delete(existing):
                return False, "删除目标冲突项目失败"
        operation = str(row.get("operation") or "move")
        method = self._guangya_api.copy if operation == "copy" else self._guangya_api.move
        if not method(source, Path(target_parent), str(source.name or "")):
            return False, f"{operation} 失败"
        for companion_info in row.get("companions") or []:
            companion = self._guangya_api.get_item(Path(str(companion_info.get("source_path") or "")))
            if not companion:
                continue
            companion_existing = self._existing_target(target_parent, str(companion.name or ""))
            if companion_existing:
                if allow_overwrite:
                    if not self._guangya_api.delete(companion_existing):
                        return False, f"字幕冲突删除失败: {companion.name}"
                else:
                    continue
            if not method(companion, Path(target_parent), str(companion.name or "")):
                return False, f"配套字幕整理失败: {companion.name}"
        return True, ""

    def api_organize_execute(self, payload: dict) -> Dict[str, Any]:
        payload = payload or {}
        if not bool(payload.get("confirm")):
            return {"success": False, "message": "请先确认执行整理计划"}
        plan_id = str(payload.get("plan_id") or "")
        plans = getattr(self, "_organize_plans", {}) or {}
        plan = plans.get(plan_id)
        if not plan:
            return {"success": False, "message": "整理计划不存在或已失效，请重新预览"}
        if time.time() - float(plan.get("created_at") or 0) > self._organize_plan_ttl:
            plans.pop(plan_id, None)
            return {"success": False, "message": "整理计划已超过 15 分钟，请重新预览"}
        allow_overwrite = bool(plan.get("allow_overwrite"))
        result_rows = []
        success_count = 0
        failed_count = 0
        for row in plan.get("items") or []:
            if row.get("status") != "ready":
                continue
            ok, error = self._execute_one_organize_item(row, allow_overwrite=allow_overwrite)
            result_rows.append({
                "source_path": row.get("source_path"),
                "target_path": row.get("target_path"),
                "operation": row.get("operation"),
                "success": ok,
                "message": error or "完成",
            })
            if ok:
                success_count += 1
            else:
                failed_count += 1
        plans.pop(plan_id, None)
        self._organize_plans = plans
        history = list(self.get_data("organize_history") or [])
        history.append({
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_path": plan.get("source_path"),
            "target_path": plan.get("target_path"),
            "success": success_count,
            "failed": failed_count,
            "results": result_rows[:100],
        })
        self.save_data("organize_history", history[-100:])
        logger.info(
            "【光鸭云盘助手】【网盘整理】执行完成：成功=%s 失败=%s 源=%s 目标=%s",
            success_count, failed_count, plan.get("source_path"), plan.get("target_path"),
        )
        return {
            "success": failed_count == 0,
            "message": f"整理完成：成功 {success_count}，失败 {failed_count}",
            "data": {"success_count": success_count, "failed_count": failed_count, "results": result_rows},
        }

    def api_organize_history(self) -> Dict[str, Any]:
        return {"success": True, "data": {"history": list(self.get_data("organize_history") or [])[-100:][::-1]}}

    def get_organizer_api(self) -> List[Dict[str, Any]]:
        """V3 JSON API；写操作均使用 POST，执行必须由 preview 产生的 plan_id 二次确认。"""
        return [
            {"path": "/organize/policies", "endpoint": self.api_organize_policies, "auth": "bear", "methods": ["GET"], "summary": "读取 MoviePilot 目录分类策略", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/folders", "endpoint": self.api_organize_folders, "auth": "bear", "methods": ["POST"], "summary": "浏览光鸭目录供网盘整理选择", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/preview", "endpoint": self.api_organize_preview, "auth": "bear", "methods": ["POST"], "summary": "按 MoviePilot 分类策略预览光鸭网盘整理计划", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/execute", "endpoint": self.api_organize_execute, "auth": "bear", "methods": ["POST"], "summary": "确认并执行光鸭网盘整理计划", "response_model": GuangYaOrganizerResponse},
            {"path": "/organize/history", "endpoint": self.api_organize_history, "auth": "bear", "methods": ["GET"], "summary": "读取最近网盘整理历史", "response_model": GuangYaOrganizerResponse},
        ]
