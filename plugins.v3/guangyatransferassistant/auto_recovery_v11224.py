"""v1.12.24 自动恢复与识别文件名前缀层。

修复三个实机回归：
1. 频道帖子/分享链接可能持续追加新集，processed_entries 不能永久阻止重新读取；
   有真实缺口时按 15 分钟窗口允许复核，最终仍由文件库存、媒体事实和 Episode Fence 去重。
2. 前序频道/分享链即使返回 handled=True，也只有在真实缺口已被媒体库、reservation、
   source claim 或电影完成事实覆盖时才允许阻断观影后备链；否则继续 Magnet/ED2K 规划。
3. 转存命名统一把实际识别文件夹名放到媒体文件名前面；迅雷/ED2K/云添加提交前改名，
   光鸭分享因 restore_share 不支持 newName，必须先完成落盘确认后再远端 rename。

同时给非更新日保留一个有界的 60 分钟主动补漏窗口：只检查日历中的 off-day / unscheduled
缺口，以及最晚明天播出的 next episode，用于覆盖资源提前放出的情况；明确未来集不会被整季轮询。
"""
from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from .legacy import _is_subtitle, _is_video, _safe_relative_path


_FORBIDDEN_NAME_V11224 = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


def _norm_name_v11224(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _safe_name_v11224(value: Any, limit: int = 120) -> str:
    text = _FORBIDDEN_NAME_V11224.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-_[]()（）【】")
    return text[: max(1, int(limit or 120))].strip()


def _prefix_name_v11224(original: Any, prefix: Any, *, limit: int = 240) -> str:
    """保留原文件名/扩展名，把识别目录名稳定放到最前面并避免重复前缀。"""
    base = _FORBIDDEN_NAME_V11224.sub(" ", str(original or "")).strip()
    marker = _safe_name_v11224(prefix)
    if not base:
        return marker[:limit]
    if not marker:
        return base[:limit]
    base_norm = _norm_name_v11224(base)
    marker_norm = _norm_name_v11224(marker)
    if marker_norm and base_norm.startswith(marker_norm):
        return base[:limit]
    joiner = f"{marker} - "
    available = max(1, int(limit or 240) - len(joiner))
    return f"{joiner}{base[:available].rstrip(' .')}"[:limit]


class GuangYaAutoRecoveryV11224Mixin:
    """只修复自动恢复与命名；不改变媒体身份、来源优先级和最终写盘硬门禁。"""

    plugin_version = "1.12.24"
    build_id = "20260910-r71"
    _processed_recheck_minutes_v11224 = 15
    _off_day_recovery_minutes_v11224 = 60

    # ------------------------------------------------------------------
    # 真实缺口：handled 只是执行返回值，不能替代媒体完成事实。
    # ------------------------------------------------------------------
    def _recovery_uncovered_v11224(self, subscribe: Any) -> Set[Any]:
        if self._is_movie_subscription(subscribe):
            try:
                if bool(self._movie_transfer_confirmed(subscribe)):
                    return set()
            except Exception:
                pass
            try:
                reservations = dict(self._pending_reservations(subscribe) or {})
                if bool(reservations.get("movie")):
                    return set()
            except Exception:
                pass
            sid = int(getattr(subscribe, "id", 0) or 0)
            try:
                rows = list((self._source_store().get("items") or {}).values())
            except Exception:
                rows = []
            for row in rows:
                if not isinstance(row, dict) or not bool(row.get("enabled", True)):
                    continue
                if int(row.get("subscribe_id") or 0) != sid:
                    continue
                state = str(row.get("state") or "")
                # new/retry 只是候选，completed 只有真实电影完成事实才能阻断；
                # dispatching/submitted/queued/waiting 才表示当前确有一个执行中的来源。
                if state in {"dispatching", "submitted", "queued", "waiting"}:
                    return set()
            return {"movie"}
        try:
            return set(self._uncovered_missing_v1125(subscribe) or set())
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # 频道增长分享：有缺口时允许周期复核，真正文件级去重仍在后面。
    # ------------------------------------------------------------------
    def _entry_processed(self, entry: Dict[str, Any], subscribe: Any = None) -> bool:
        processed = bool(super()._entry_processed(entry, subscribe))
        if not processed or subscribe is None:
            return processed
        try:
            gap = self._recovery_uncovered_v11224(subscribe)
        except Exception:
            gap = set()
        if not gap:
            return True
        key = self._processed_entry_key(entry, subscribe)
        row = dict((self.get_data("processed_entries") or {}).get(key) or {})
        status = str(row.get("status") or "").strip().lower()
        # filtered/ignored 是明确策略结论；只有“曾经无新增/曾经转过”允许重新看同一增长链接。
        if status not in {"synced", "no_new_episode", "transferred", "legacy_synced", "processed"}:
            return True
        updated = None
        try:
            updated = self._parse_datetime(row.get("time"))
        except Exception:
            updated = None
        if updated is not None:
            age = (datetime.datetime.now() - updated).total_seconds()
            if age < max(300, int(self._processed_recheck_minutes_v11224) * 60):
                return True
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【频道增长复核v1.12.24】#%s %s 仍有缺口=%s；已处理分享达到复核窗口，重新读取分享内容，文件级库存继续防重复",
            int(getattr(subscribe, "id", 0) or 0),
            str(getattr(subscribe, "name", "") or ""),
            ",".join(str(v) for v in sorted(gap, key=str)) or "movie",
        )
        return False

    # ------------------------------------------------------------------
    # handled 静默阻断恢复：真实缺口存在时继续观影后备来源。
    # ------------------------------------------------------------------
    def _try_transfer_subscription_inner(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        result = dict(super()._try_transfer_subscription_inner(
            subscribe,
            force=force,
            refresh_channel=refresh_channel,
        ) or {})
        if "viewing_external" in result or bool(result.get("completed")) or bool(result.get("pending")):
            return result
        try:
            allowed, _ = self._subscription_static_guard(subscribe)
        except Exception:
            allowed = True
        if not allowed:
            return result
        gap = self._recovery_uncovered_v11224(subscribe)
        if not gap:
            return result

        reader = getattr(self, "_route_source_mode_value_v1115", None)
        mode = str(reader() if callable(reader) else getattr(self, "_route_source_mode_v1115", "") or "")
        if bool(result.get("handled")):
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【自动恢复v1.12.24】#%s %s 前序返回 handled=True 但真实缺口仍存在=%s；不再把 handled 当作完成事实",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                ",".join(str(v) for v in sorted(gap, key=str)) or "movie",
            )

        # 5 分钟 channel_event 仍保持纯被动；把 handled 修正为 False，让下一次缓存补偿能继续恢复。
        if mode == "channel_event":
            if bool(result.get("handled")):
                result["handled"] = False
                result["message"] = f"{str(result.get('message') or '频道本轮未形成真实覆盖')}；仍有真实缺口，保留自动恢复"
            return result

        if not bool(getattr(self, "_provider_auto_search", True)):
            return result
        try:
            viewing = dict(self._dispatch_viewing_external_v1113(subscribe) or {})
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【自动恢复v1.12.24】#%s %s 继续观影后备来源异常：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(err)[:300],
            )
            viewing = {"success": False, "actions": [], "message": str(err)}
        if viewing.get("actions"):
            return {
                **result,
                "success": True,
                "handled": True,
                "viewing_external": viewing,
                "message": f"{str(result.get('message') or '前序链未形成真实覆盖')}；{str(viewing.get('message') or '观影后备来源已入队')}",
            }
        # 没有真实入队就不再伪装成“已处理完成”，下一轮仍可重试。
        result["handled"] = False
        result["viewing_external"] = viewing
        return result

    # ------------------------------------------------------------------
    # 非更新日/提前放出：每 60 分钟只补 off-day / unscheduled / 最晚明日 next episode。
    # ------------------------------------------------------------------
    @staticmethod
    def _v11224_iso_date(value: Any):
        text = str(value or "").strip()[:10]
        if not text:
            return None
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return None

    def _smart_pull_due_ids_v1125(self) -> List[int]:
        due = set(int(v) for v in (super()._smart_pull_due_ids_v1125() or []) if int(v or 0) > 0)
        try:
            search_state = dict(self._external_search_state_v1114() or {})
        except Exception:
            search_state = {}
        try:
            gate_state = dict(self.get_data("airing_gate_state_v1120") or {})
        except Exception:
            gate_state = {}
        now = time.time()
        today = datetime.date.today()
        added: List[int] = []
        for subscribe in self._active_selected_subscriptions_v1125() or []:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0 or sid in due or self._is_movie_subscription(subscribe):
                continue
            uncovered = set(self._recovery_uncovered_v11224(subscribe) or set())
            if not uncovered:
                continue
            row = dict(gate_state.get(str(sid)) or {})
            recovery = {
                int(v) for v in [*(row.get("off_day_missing") or []), *(row.get("unscheduled_missing") or [])]
                if str(v).isdigit() and int(v) > 0
            }.intersection({int(v) for v in uncovered if isinstance(v, int) or str(v).isdigit()})
            next_episode = int(row.get("next_episode") or 0)
            next_date = self._v11224_iso_date(row.get("next_air_at"))
            if next_episode > 0 and next_episode in uncovered and next_date and next_date <= today + datetime.timedelta(days=1):
                recovery.add(next_episode)
            if not recovery:
                continue
            state_row = dict(search_state.get(str(sid)) or {})
            try:
                last_at = float(state_row.get("last_at") or 0)
            except (TypeError, ValueError):
                last_at = 0.0
            cooldown = max(1800, int(self._off_day_recovery_minutes_v11224) * 60)
            if last_at and now - last_at < cooldown:
                continue
            due.add(sid)
            added.append(sid)
        if added:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【提前资源补漏v1.12.24】非严格更新日仍有可恢复缺口，加入每小时主动检查：%s",
                ",".join(f"#{sid}" for sid in sorted(added)),
            )
        return sorted(due)

    # ------------------------------------------------------------------
    # 命名：实际识别文件夹名必须出现在最前面。
    # ------------------------------------------------------------------
    def _recognition_folder_name_v11224(self, subscribe: Any) -> str:
        target = str(self._target_path(subscribe) or "").replace("\\", "/").rstrip("/")
        if bool(getattr(self, "_create_media_folder", False)) and target:
            folder = target.rsplit("/", 1)[-1]
            if folder:
                return _safe_name_v11224(folder)
        name = _safe_name_v11224(getattr(subscribe, "name", "") or "")
        year = _safe_name_v11224(getattr(subscribe, "year", "") or "")
        return _safe_name_v11224(f"{name} ({year})" if name and year else name)

    def _xunlei_prefix_v11224(self, subscribe: Any) -> str:
        prefix = self._recognition_folder_name_v11224(subscribe)
        season = getattr(subscribe, "season", None)
        if season not in (None, ""):
            try:
                prefix = _safe_name_v11224(f"{prefix} S{int(season):02d}")
            except (TypeError, ValueError):
                pass
        return prefix

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        resolved = dict(super()._resolve_offline_source(source, subscribe) or {})
        original = str(
            source.get("original_resolved_name")
            or resolved.get("resolved_name")
            or source.get("resolved_name")
            or source.get("name")
            or source.get("label")
            or ""
        ).strip()
        prefix = self._recognition_folder_name_v11224(subscribe)
        desired = _prefix_name_v11224(original, prefix)
        if desired and desired != original:
            source["label"] = desired
            source_id = str(source.get("id") or "")
            if source_id:
                self._update_source(
                    source_id,
                    requested_name=desired,
                    original_resolved_name=original[:300],
                    recognition_prefix_v11224=prefix[:140],
                )
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【识别命名v1.12.24】云添加名称：识别目录=%s 原名=%s 新名=%s",
                prefix[:140] or "-",
                original[:180] or "-",
                desired[:220],
            )
        return resolved

    def _rapid_transfer_xunlei_file(self, subscribe: Any, row: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(row or {})
        old_name = str(prepared.get("name") or str(prepared.get("path") or "").rsplit("/", 1)[-1] or "file").strip()
        prefix = self._xunlei_prefix_v11224(subscribe)
        desired = _prefix_name_v11224(old_name, prefix)
        if desired and desired != old_name:
            prepared["name"] = desired
            raw_path = str(prepared.get("path") or old_name).replace("\\", "/")
            parent = raw_path.rsplit("/", 1)[0] if "/" in raw_path else ""
            prepared["path"] = f"{parent}/{desired}" if parent else desired
        return dict(super()._rapid_transfer_xunlei_file(subscribe, prepared) or {})

    def _restore_subscribe_v11224(self, job_key: str = "") -> Any:
        local = getattr(self, "_core_pipeline_local_v11214", None)
        subscribe = getattr(local, "subscribe", None) if local is not None else None
        if subscribe is not None:
            return subscribe
        if job_key:
            try:
                row = dict(self._get_job_state(job_key) or {})
                sid = int(row.get("subscribe_id") or 0)
                if sid > 0:
                    return self._find_subscription(sid)
            except Exception:
                pass
        return None

    @staticmethod
    def _rename_ok_v11224(value: Any) -> bool:
        if value is True:
            return True
        if not isinstance(value, dict) or value.get("error"):
            return False
        return value.get("code") in (None, 0, "0", 200, "200") and str(value.get("msg") or value.get("message") or "").lower() not in {"error", "failed", "fail"}

    def _rename_restored_media_v11224(
        self,
        subscribe: Any,
        save_path: str,
        items: Iterable[Dict[str, Any]],
    ) -> int:
        if subscribe is None:
            return 0
        prefix = self._recognition_folder_name_v11224(subscribe)
        if not prefix:
            return 0
        client, api = self._get_guangya_runtime()
        if not client or not api or not callable(getattr(client, "rename", None)):
            return 0
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in items or []:
            path = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "")
            if not (_is_video(path) or _is_subtitle(path)):
                continue
            groups.setdefault(str(item.get("target_parent") or ""), []).append(dict(item))
        renamed = 0
        base = str(save_path or "/").replace("\\", "/").rstrip("/") or "/"
        for relative_parent, group in groups.items():
            parent = _safe_relative_path(relative_parent)
            folder_path = (base.rstrip("/") + ("/" + parent if parent else "")) or "/"
            try:
                folder = api.get_item(Path(folder_path)) if callable(getattr(api, "get_item", None)) else None
                if folder is None:
                    continue
                remote_rows = list(api.list(folder) or []) if callable(getattr(api, "list", None)) else []
            except Exception as err:
                self._plugin_log("WARNING", "【光鸭转存助手】【识别命名v1.12.24】读取已转存目录失败：%s (%s)", folder_path, str(err)[:180])
                continue
            remote_by_name = {str(getattr(row, "name", "") or ""): row for row in remote_rows}
            for item in group:
                path = str(item.get("effective_path") or item.get("relative_path") or item.get("name") or "").replace("\\", "/")
                old_name = path.rsplit("/", 1)[-1]
                desired = _prefix_name_v11224(old_name, prefix)
                if not desired or desired == old_name:
                    continue
                remote = remote_by_name.get(old_name)
                file_id = str(getattr(remote, "fileid", "") or "") if remote is not None else ""
                if not file_id:
                    continue
                try:
                    response = client.rename(file_id, desired)
                    if self._rename_ok_v11224(response):
                        renamed += 1
                        self._plugin_log(
                            "INFO",
                            "【光鸭转存助手】【识别命名v1.12.24】分享落盘后重命名：%s -> %s",
                            old_name[:180],
                            desired[:220],
                        )
                    else:
                        self._plugin_log("WARNING", "【光鸭转存助手】【识别命名v1.12.24】分享已成功但重命名未确认：%s -> %s", old_name[:160], desired[:200])
                except Exception as err:
                    self._plugin_log("WARNING", "【光鸭转存助手】【识别命名v1.12.24】分享已成功但重命名异常：%s", str(err)[:220])
        return renamed

    def _restore_items(
        self,
        probe: Dict[str, Any],
        save_path: str,
        items: List[Dict[str, Any]],
        job_key: str = "",
    ) -> Dict[str, Any]:
        result = dict(super()._restore_items(probe, save_path, items, job_key=job_key) or {})
        completed = list(result.get("completed_items") or [])
        if completed:
            subscribe = self._restore_subscribe_v11224(job_key)
            renamed = self._rename_restored_media_v11224(subscribe, save_path, completed)
            if renamed:
                result["renamed_media_v11224"] = renamed
        return result


__all__ = ["GuangYaAutoRecoveryV11224Mixin", "_prefix_name_v11224"]
