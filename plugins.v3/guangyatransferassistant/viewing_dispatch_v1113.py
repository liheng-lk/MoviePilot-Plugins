"""v1.10.13 观影资源执行、命名补强与完整日志层。

目标：
- 迅雷分享仍然只走光鸭 userres 秒传，绝不转成本地/OSS 下载；
- 观影返回的 Magnet/ED2K 不再只停留在搜索候选，而是绑定当前 MoviePilot
  订阅并进入光鸭 cloudcollection 原生云添加；
- 修复 GYING downlist.list.k 漂移导致合法 BTIH 被误过滤：只要 list.m 是合法
  32/40 位 BTIH，就允许既有解析器把它构造成 Magnet；
- 观影来源创建远端文件时保留原始名称，并追加观影搜索得到的资源名称/影视名称，
  提高 MoviePilot/光鸭整理对弱命名剧集的识别率；
- 秒传、观影候选规划、云添加、命名和回退全过程输出可诊断日志。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .source_types_v180 import SOURCE_INFLIGHT_STATES, normalize_source_uri


_BTIH_V1113 = re.compile(r"^(?:[0-9A-Fa-f]{40}|[A-Z2-7a-z2-7]{32})$")
_FORBIDDEN_NAME_V1113 = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")
_MEDIA_SUFFIXES_V1113 = {
    ".mkv", ".mp4", ".ts", ".m2ts", ".mts", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".iso", ".rmvb", ".m4v", ".mpg", ".mpeg", ".vob", ".srt", ".ass",
    ".ssa", ".vtt", ".sub", ".sup", ".smi", ".idx",
}
_ACTIVE_VIEWING_SOURCE_STATES_V1113 = {
    "new", "retry", "dispatching", "submitted", "queued", "waiting", "completed"
}


def _nested_dict_ref_v1113(payload: Any, key: str) -> Optional[Dict[str, Any]]:
    """返回真实嵌套 dict 引用，而不是副本。"""
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        for child in payload.values():
            found = _nested_dict_ref_v1113(child, key)
            if found is not None:
                return found
    elif isinstance(payload, (list, tuple)):
        for child in payload:
            found = _nested_dict_ref_v1113(child, key)
            if found is not None:
                return found
    return None


def _norm_name_v1113(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _safe_tag_v1113(value: Any, limit: int = 96) -> str:
    text = _FORBIDDEN_NAME_V1113.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-_[]()（）【】")
    return text[: max(1, int(limit or 96))].strip()


def _append_tag_to_name_v1113(original: Any, tag: Any, *, limit: int = 240) -> str:
    """保留原名和扩展名，在扩展名前追加识别标签。"""
    base = _FORBIDDEN_NAME_V1113.sub(" ", str(original or "")).strip()
    extra = _safe_tag_v1113(tag)
    if not base:
        return extra[:limit]
    if not extra:
        return base[:limit]
    base_norm = _norm_name_v1113(base)
    tag_norm = _norm_name_v1113(extra)
    if tag_norm and (tag_norm in base_norm or base_norm in tag_norm):
        return base[:limit]

    suffix = ""
    stem = base
    dot = base.rfind(".")
    if dot > 0:
        candidate = base[dot:].lower()
        if candidate in _MEDIA_SUFFIXES_V1113:
            suffix = base[dot:]
            stem = base[:dot]

    marker = f" [{extra}]"
    max_stem = max(1, int(limit or 240) - len(marker) - len(suffix))
    stem = stem[:max_stem].rstrip(" .")
    return f"{stem}{marker}{suffix}"[:limit]


class GuangYaViewingDispatchV1113Mixin:
    """观影搜索结果真正进入固定转存执行链。"""

    build_id = "20260902-r24"

    # ------------------------------------------------------------------
    # GYING Magnet 字段兼容
    # ------------------------------------------------------------------
    def _gying_detail(
        self,
        session,
        node: str,
        resource_type: str,
        resource_id: str,
        referer: str,
    ) -> Dict[str, Any]:
        payload = super()._gying_detail(session, node, resource_type, resource_id, referer)
        down = _nested_dict_ref_v1113(payload, "downlist")
        listing = down.get("list") if isinstance(down, dict) else None
        if not isinstance(listing, dict):
            return payload
        magnets = list(listing.get("m") or []) if isinstance(listing.get("m"), (list, tuple)) else []
        if not magnets:
            return payload
        kinds = list(listing.get("k") or []) if isinstance(listing.get("k"), (list, tuple)) else []
        if len(kinds) < len(magnets):
            kinds.extend([-1] * (len(magnets) - len(kinds)))
        changed = 0
        valid = 0
        for index, raw in enumerate(magnets):
            btih = str(raw or "").strip()
            if not _BTIH_V1113.fullmatch(btih):
                continue
            valid += 1
            try:
                current = int(kinds[index])
            except (TypeError, ValueError):
                current = -1
            if current != 0:
                kinds[index] = 0
                changed += 1
        if changed:
            listing["k"] = kinds
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影】Magnet字段兼容：详情=%s/%s 有效BTIH=%s 修正k漂移=%s；后续交给光鸭原生云添加",
                resource_type,
                resource_id,
                valid,
                changed,
            )
        return payload

    # ------------------------------------------------------------------
    # 远端命名：原名 + 观影搜索资源名
    # ------------------------------------------------------------------
    def _viewing_name_tag_v1113(self, source: Dict[str, Any], subscribe: Any) -> str:
        resource_name = _safe_tag_v1113(source.get("search_resource_name") or source.get("name") or "")
        search_title = _safe_tag_v1113(source.get("search_title") or getattr(subscribe, "name", "") or "")
        if resource_name and search_title:
            if _norm_name_v1113(search_title) not in _norm_name_v1113(resource_name):
                return _safe_tag_v1113(f"{search_title} - {resource_name}")
            return resource_name
        return resource_name or search_title

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        resolved = super()._resolve_offline_source(source, subscribe)
        if not str(source.get("origin") or "").startswith("viewing"):
            return resolved
        original = str(resolved.get("resolved_name") or source.get("name") or "").strip()
        tag = self._viewing_name_tag_v1113(source, subscribe)
        desired = _append_tag_to_name_v1113(original, tag)
        if desired and desired != original:
            # multisource_v180 在 create_task 前读取同一个 source dict 的 label。
            # 这里就地改写，让 newName 直接使用“原名 + 搜索资源名”，并持久化用于完成后核对。
            source["label"] = desired
            source_id = str(source.get("id") or "")
            if source_id:
                self._update_source(
                    source_id,
                    requested_name=desired,
                    original_resolved_name=original[:300],
                    search_name_tag=tag[:160],
                )
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【命名】观影云添加名称：source=%s 原名=%s 追加=%s 新名=%s",
                source_id or "-",
                original[:180] or "-",
                tag[:160] or "-",
                desired[:220],
            )
        return resolved

    @staticmethod
    def _rename_result_ok_v1113(value: Any) -> bool:
        if value is True:
            return True
        if not isinstance(value, dict):
            return False
        if value.get("error"):
            return False
        msg = str(value.get("msg") or value.get("message") or "").strip().lower()
        if msg in {"success", "ok", "成功"}:
            return True
        return value.get("code") in (None, 0, "0", 200, "200") and not msg

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        result = super()._poll_offline_source(source)
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict) or str(data.get("state") or "") != "completed":
            return result
        latest = dict(self._source_store()["items"].get(str(source.get("id") or "")) or data)
        if not str(latest.get("origin") or "").startswith("viewing"):
            return result
        desired = str(latest.get("requested_name") or "").strip()
        file_id = str(latest.get("file_id") or "").strip()
        current = str(latest.get("resolved_name") or "").strip()
        if not desired or not file_id or _norm_name_v1113(desired) == _norm_name_v1113(current):
            return result

        client, _ = self._get_guangya_runtime()
        rename = getattr(client, "rename", None) if client else None
        response: Any = None
        try:
            if callable(rename):
                response = rename(file_id, desired)
            else:
                request = getattr(client, "_request", None) if client else None
                if not callable(request):
                    raise RuntimeError("光鸭客户端缺少 rename 能力")
                base_url = str(getattr(client, "API_BASE_URL", "https://api.guangyapan.com") or "").rstrip("/")
                response = request(
                    method="POST",
                    url=f"{base_url}/nd.bizuserres.s/v1/file/rename",
                    data={"fileId": file_id, "newName": desired},
                )
            if self._rename_result_ok_v1113(response):
                updated = self._update_source(
                    str(latest.get("id") or ""),
                    resolved_name=desired,
                    renamed_name=desired,
                    rename_at=self._now_text(),
                    rename_error="",
                )
                if isinstance(result, dict) and isinstance(updated, dict):
                    result["data"] = updated
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【命名】云添加完成后远端名称确认：fileId=%s %s -> %s",
                    file_id,
                    current[:180] or "-",
                    desired[:220],
                )
            else:
                message = str((response or {}).get("msg") or (response or {}).get("message") or response or "rename 未确认")[:240] if isinstance(response, dict) else str(response or "rename 未确认")[:240]
                self._update_source(str(latest.get("id") or ""), rename_error=message)
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【命名】云添加已完成但远端重命名未确认：fileId=%s 当前=%s 目标=%s 原因=%s",
                    file_id,
                    current[:160] or "-",
                    desired[:180],
                    message,
                )
        except Exception as err:
            self._update_source(str(latest.get("id") or ""), rename_error=str(err)[:300])
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【命名】云添加已完成但重命名异常：fileId=%s 目标=%s 错误=%s",
                file_id,
                desired[:180],
                str(err)[:260],
            )
        return result

    # ------------------------------------------------------------------
    # 迅雷仍只秒传；补命名和逐文件日志
    # ------------------------------------------------------------------
    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(row or {})
        old_name = str(prepared.get("name") or str(prepared.get("path") or "").rsplit("/", 1)[-1] or "file").strip()
        canonical = str(getattr(subscribe, "name", "") or "").strip()
        year = str(getattr(subscribe, "year", "") or "").strip()
        season = getattr(subscribe, "season", None)
        tag = " ".join(value for value in (canonical, year, f"S{int(season):02d}" if season not in (None, "") else "") if str(value or "").strip())
        new_name = _append_tag_to_name_v1113(old_name, tag)
        if new_name and new_name != old_name:
            prepared["name"] = new_name
            raw_path = str(prepared.get("path") or old_name).replace("\\", "/")
            parent = raw_path.rsplit("/", 1)[0] if "/" in raw_path else ""
            prepared["path"] = f"{parent}/{new_name}" if parent else new_name
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【迅雷秒传】文件开始：原名=%s 远端名=%s size=%s GCID=%s；只尝试秒传，不做普通下载",
            old_name[:180] or "-",
            str(prepared.get("name") or "")[:220],
            int(prepared.get("size") or 0),
            "yes" if prepared.get("gcid") else "no",
        )
        result = super()._rapid_transfer_xunlei_file(subscribe, prepared)
        self._plugin_log(
            "INFO" if bool((result or {}).get("success")) else "WARNING",
            "【光鸭转存助手】【迅雷秒传】文件结果：name=%s success=%s task=%s 原因=%s",
            str(prepared.get("name") or "")[:200],
            bool((result or {}).get("success")),
            str((result or {}).get("task_id") or "-")[:80],
            str((result or {}).get("reason") or "-")[:260],
        )
        return result

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【迅雷秒传】#%s 预检开始：%s；迅雷只作为秒传来源",
            sid,
            str(getattr(subscribe, "name", "") or ""),
        )
        result = dict(super()._dispatch_xunlei_flash(subscribe) or {})
        self._plugin_log(
            "INFO" if bool(result.get("success")) else "WARNING",
            "【光鸭转存助手】【迅雷秒传】#%s 预检结束：shares=%s attempted=%s success_files=%s episodes=%s handled=%s 信息=%s",
            sid,
            int(result.get("shares") or 0),
            int(result.get("attempted_files") or 0),
            int(result.get("successful_files") or 0),
            ",".join(str(v) for v in (result.get("episodes") or [])) or "-",
            bool(result.get("handled")),
            str(result.get("message") or "-")[:260],
        )
        for index, error in enumerate(list(result.get("errors") or [])[:20], start=1):
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷秒传】#%s 失败明细 %s/%s：%s",
                sid,
                index,
                min(len(list(result.get("errors") or [])), 20),
                str(error)[:360],
            )
        return result

    # ------------------------------------------------------------------
    # 观影 Magnet/ED2K -> 光鸭原生 cloudcollection
    # ------------------------------------------------------------------
    def _viewing_external_candidates_v1113(self, subscribe: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        keyword = str(self._provider_keyword(subscribe) or "").strip()
        rows, state = self._gying_raw_results(keyword, force=False)
        executable: List[Dict[str, Any]] = []
        counts = {"magnet": 0, "ed2k": 0, "xunlei": 0, "other_pan": 0, "invalid": 0}
        for raw in list(rows or []):
            row = dict(raw or {})
            uri = str(row.get("url") or row.get("uri") or "").strip()
            lowered = uri.lower()
            if "pan.xunlei.com/s/" in lowered:
                counts["xunlei"] += 1
                continue
            try:
                normalized = normalize_source_uri(uri)
            except Exception:
                if lowered.startswith(("http://", "https://")):
                    counts["other_pan"] += 1
                else:
                    counts["invalid"] += 1
                continue
            source_type = str(normalized.get("type") or "")
            if source_type not in {"magnet", "ed2k"}:
                counts["invalid"] += 1
                continue
            counts[source_type] += 1
            row.update(normalized)
            row["uri"] = str(normalized.get("uri") or uri)
            executable.append(row)
        executable.sort(key=lambda row: (0 if str(row.get("type") or "") == "magnet" else 1, -int(row.get("seeds") or -1)))
        return executable, {"keyword": keyword, "counts": counts, "state": dict(state or {}), "raw": len(rows or [])}

    def _dispatch_viewing_external_v1113(self, subscribe: Any) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return {"success": False, "actions": [], "message": "订阅 ID 无效"}
        if not bool(getattr(self, "_provider_auto_search", True)):
            return {"success": False, "actions": [], "message": "观影自动搜索已关闭"}
        if not bool(getattr(self, "_external_auto_dispatch", True)):
            return {"success": False, "actions": [], "message": "Magnet/ED2K 自动云添加已关闭"}

        is_movie = bool(self._is_movie_subscription(subscribe))
        missing = set(int(v) for v in (self._subscription_missing_episodes(subscribe) or []) if int(v or 0) > 0)
        reservations = dict(self._pending_reservations(subscribe) or {})
        reserved = set(int(v) for v in (reservations.get("episodes") or set()) if int(v or 0) > 0)
        active_claims = set(int(v) for v in (self._active_source_claims(sid) or set()) if int(v or 0) > 0)
        uncovered = missing - reserved - active_claims

        if is_movie and bool(reservations.get("movie")):
            return {"success": True, "actions": [], "message": "已有光鸭/迅雷任务覆盖电影目标"}
        if is_movie:
            prior_movie_sources = [
                row for row in (self._source_store().get("items") or {}).values()
                if isinstance(row, dict)
                and int(row.get("subscribe_id") or 0) == sid
                and str(row.get("origin") or "") == "viewing_auto"
                and str(row.get("state") or "new") in _ACTIVE_VIEWING_SOURCE_STATES_V1113
            ]
            if prior_movie_sources:
                return {
                    "success": True,
                    "actions": [],
                    "message": "电影已有观影云添加候选，等待成功/失败核验后再决定是否回退",
                }
        if not is_movie and not uncovered:
            return {"success": True, "actions": [], "message": "当前缺集已被已完成/在途任务覆盖"}

        candidates, meta = self._viewing_external_candidates_v1113(subscribe)
        counts = dict(meta.get("counts") or {})
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【观影执行】#%s 搜索资源进入执行规划：关键词=%s 原始=%s Magnet=%s ED2K=%s 迅雷=%s 其它网盘=%s missing=%s reserved=%s claimed=%s",
            sid,
            str(meta.get("keyword") or "-")[:180],
            int(meta.get("raw") or 0),
            int(counts.get("magnet") or 0),
            int(counts.get("ed2k") or 0),
            int(counts.get("xunlei") or 0),
            int(counts.get("other_pan") or 0),
            ",".join(str(v) for v in sorted(missing)) or "-",
            ",".join(str(v) for v in sorted(reserved)) or "-",
            ",".join(str(v) for v in sorted(active_claims)) or "-",
        )
        if not candidates:
            return {
                "success": False,
                "actions": [],
                "message": "观影没有可交给光鸭原生云添加的 Magnet/ED2K 候选",
                "counts": counts,
            }

        actions: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for candidate in candidates:
            source_type = str(candidate.get("type") or "")
            name = str(candidate.get("name") or "").strip()
            search_title = str(candidate.get("search_title") or getattr(subscribe, "name", "") or "").strip()
            if not self._provider_candidate_matches(subscribe, candidate):
                reason = f"{source_type} 标题不匹配：{search_title or name}"
                skipped.append(reason)
                self._plugin_log("INFO", "【光鸭转存助手】【观影执行】#%s 跳过：%s", sid, reason[:320])
                continue

            identity = str(candidate.get("identity") or "")
            existing = self._existing_source(sid, source_type, identity)
            existing_state = str(existing.get("state") or "")
            if existing and existing_state in _ACTIVE_VIEWING_SOURCE_STATES_V1113:
                reason = f"{source_type} 已存在 source={existing.get('id')} state={existing_state}"
                skipped.append(reason)
                self._plugin_log("INFO", "【光鸭转存助手】【观影执行】#%s 复用/跳过：%s", sid, reason)
                continue
            if existing_state in {"failed", "needs_review", "disabled"}:
                reason = f"{source_type} 历史候选 state={existing_state}，继续下一个"
                skipped.append(reason)
                self._plugin_log("INFO", "【光鸭转存助手】【观影执行】#%s 跳过：%s", sid, reason)
                continue

            if is_movie:
                target: set[int] = set()
            else:
                probe_entry = {"episode_hint": str(candidate.get("episode_hint") or "")}
                target = set(self._candidate_target_episodes(subscribe, probe_entry, candidate, uncovered))
                if not target:
                    reason = f"{source_type} 无法覆盖当前缺集：{name or search_title}"
                    skipped.append(reason)
                    self._plugin_log("INFO", "【光鸭转存助手】【观影执行】#%s 跳过：%s", sid, reason[:320])
                    continue

            row = self._upsert_source(
                sid,
                str(candidate.get("uri") or ""),
                label="",
                origin="viewing_auto",
                auto_dispatch=True,
                resource_group_id=f"viewing:{candidate.get('resource_type') or 'res'}:{candidate.get('resource_id') or identity}"[:80],
                target_episodes=sorted(target),
                episode_hint=str(candidate.get("episode_hint") or ""),
                source_label="GYING",
                message_id="",
                candidate_rank=1 if source_type == "magnet" else 2,
            )
            source_id = str(row.get("id") or "")
            updated = self._update_source(
                source_id,
                search_title=search_title[:200],
                search_resource_name=name[:240],
                viewing_resource_type=str(candidate.get("resource_type") or "")[:40],
                viewing_resource_id=str(candidate.get("resource_id") or "")[:80],
                viewing_search_keyword=str(meta.get("keyword") or "")[:240],
                origin="viewing_auto",
            ) or row
            action = {
                "source_id": source_id,
                "type": source_type,
                "episodes": sorted(target),
                "search_title": search_title,
                "resource_name": name,
            }
            actions.append(action)
            notify_selected = getattr(self, "_notify_acquisition_v1113", None)
            if callable(notify_selected) and not updated.get("selection_notified_at"):
                planned = ", ".join(f"E{value:02d}" for value in sorted(target)) or "电影正片"
                lines = [
                    f"媒体：{getattr(subscribe, 'name', '')}",
                    f"来源：{source_type.upper()} → 光鸭原生云添加",
                    f"已选资源：{(name or search_title)[:180]}",
                    f"计划补充：{planned}",
                    "状态：等待光鸭任务完成后核验；期间不会并行提交相似资源",
                ]
                if notify_selected("🎯 已选择光鸭云资源", lines):
                    self._update_source(source_id, selection_notified_at=self._now_text())
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【观影执行】#%s 已绑定并提交：type=%s source=%s target=%s 搜索标题=%s 资源名=%s；执行器=光鸭cloudcollection",
                sid,
                source_type.upper(),
                source_id,
                ",".join(str(v) for v in sorted(target)) or "movie",
                search_title[:160] or "-",
                name[:200] or "-",
            )
            self._spawn_source_dispatch(source_id)
            if is_movie:
                break
            uncovered -= target
            if not uncovered:
                break

        self._plugin_log(
            "INFO" if actions else "WARNING",
            "【光鸭转存助手】【观影执行】#%s 规划结束：actions=%s remaining=%s skipped=%s",
            sid,
            len(actions),
            ",".join(str(v) for v in sorted(uncovered)) or "-",
            len(skipped),
        )
        return {
            "success": bool(actions),
            "actions": actions,
            "remaining": sorted(uncovered),
            "skipped": skipped[:30],
            "counts": counts,
            "message": f"观影已生成 {len(actions)} 个光鸭原生云添加任务" if actions else "观影候选已检查，但没有可安全执行的 Magnet/ED2K",
        }

    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        lower = dict(super()._try_transfer_subscription_inner(
            subscribe,
            force=force,
            refresh_channel=refresh_channel,
        ) or {})
        # 只有下层真正成功并完整接管才停止。legacy 的“频道没匹配”会返回
        # success=False, handled=True，不能因此阻止观影 Magnet/ED2K 回退。
        if bool(lower.get("success")) and bool(lower.get("handled")):
            return lower
        try:
            viewing = self._dispatch_viewing_external_v1113(subscribe)
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【观影执行】#%s 自动云添加规划异常：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(err)[:360],
            )
            viewing = {"success": False, "actions": [], "message": str(err)}
        if viewing.get("actions"):
            return {
                **lower,
                "success": True,
                "handled": True,
                "viewing_external": viewing,
                "message": f"{str(lower.get('message') or '前序来源已检查')}；{viewing.get('message')}",
            }
        return {**lower, "viewing_external": viewing}


__all__ = [
    "GuangYaViewingDispatchV1113Mixin",
    "_append_tag_to_name_v1113",
]
