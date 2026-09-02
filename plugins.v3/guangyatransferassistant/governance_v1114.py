"""v1.10.14 外部检索治理、完成闭环与资源质量门禁。

目标：
- 自动周期触发在订阅已经执行中时只合并，不再生成“补偿重查”自激循环；
- 同一订阅的观影/迅雷外部检索默认至少间隔 180 分钟，人工强制检查可绕过；
- 已无缺集时先尝试完成订阅，禁止为了“确认一下”继续访问外部资源站；
- 迅雷秒传、Magnet/ED2K cloudcollection 完成后主动触发 MoviePilot 订阅完成流程；
- 统一过滤广告伪视频、CAM/TS/TC 等低质标签和显式低分辨率；可选要求字幕信号；
- BPHDTV 广告伪 MKV 无条件从 Magnet/迅雷拆包选择中排除。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .legacy import _is_subtitle, _is_video
from .runtime_fix_v1113 import GuangYaRuntimeFixV1113Mixin


_POISON_MEDIA_RE_V1114 = re.compile(
    r"bphdtv\.com|更多电视剧集下载请访问|更多剧集打包下载请访问",
    re.I,
)
_LOW_QUALITY_RE_V1114 = re.compile(
    r"(?:^|[\s._\-\[\]()])(?:cam|camrip|hdcam|hdts|telesync|telecine|tc|dvdscr|dvdscreener|scr|r5|枪版|抢先版)(?:$|[\s._\-\[\]()])",
    re.I,
)
_RESOLUTION_RE_V1114 = re.compile(r"(?<!\d)(360|480|540|576|720|1080|1440|2160|4320)p(?!\d)", re.I)
_SUBTITLE_SIGNAL_RE_V1114 = re.compile(
    r"(?:中字|中文字幕|简中|繁中|简繁|双语|内封|内嵌|字幕|chs|cht|ch[ist]?|sub(?:title)?s?)",
    re.I,
)
_AUTO_TRIGGER_HINTS_V1114 = (
    "后台检查",
    "宿主订阅搜索分流",
    "宿主批量订阅搜索分流",
    "后台合并补偿",
    "频道故障自动恢复",
    "启动检查",
    "定时",
)
_MANUAL_TRIGGER_HINTS_V1114 = ("手动", "人工", "立即", "api", "控制台", "按钮")


def _safe_positive_int_v1114(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


class GuangYaGovernanceV1114Mixin(GuangYaRuntimeFixV1113Mixin):
    """最终资源治理层。"""

    build_id = "20260902-r25"

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        self._external_search_cooldown_minutes_v1114 = _safe_positive_int_v1114(
            config.get("external_search_cooldown_minutes"), 180, 15, 1440
        )
        self._quality_min_resolution_v1114 = _safe_positive_int_v1114(
            config.get("quality_min_resolution"), 720, 0, 4320
        )
        self._quality_min_video_mb_v1114 = _safe_positive_int_v1114(
            config.get("quality_min_video_mb"), 0, 0, 10000
        )
        self._quality_require_subtitle_v1114 = bool(config.get("quality_require_subtitle", False))
        self._quality_reject_low_tags_v1114 = bool(config.get("quality_reject_low_tags", True))
        self._quality_custom_reject_v1114 = str(config.get("quality_custom_reject") or "").strip()
        self._external_round_allowed_v1114: Dict[int, bool] = {}
        return super().init_plugin(config)

    # ------------------------------------------------------------------
    # 后台合并：自动触发不允许执行中订阅产生补偿自激
    # ------------------------------------------------------------------
    @staticmethod
    def _manual_trigger_v1114(trigger: str) -> bool:
        lowered = str(trigger or "").lower()
        return any(token in lowered for token in _MANUAL_TRIGGER_HINTS_V1114)

    @staticmethod
    def _automatic_trigger_v1114(trigger: str) -> bool:
        text = str(trigger or "")
        return any(token in text for token in _AUTO_TRIGGER_HINTS_V1114)

    def _queue_async_route_check(self, sids: Iterable[int], trigger: str = "后台检查") -> None:
        ids = {
            int(value) for value in sids
            if str(value).isdigit() and int(value) > 0
        }
        if not ids:
            return
        # 周期/宿主触发如果订阅已经在本轮执行，直接合并丢弃该重复事件。
        # 人工操作仍允许父层保留一次补偿重查。
        if self._automatic_trigger_v1114(trigger) and not self._manual_trigger_v1114(trigger):
            self._ensure_reliability_state()
            lock = getattr(self, "_async_route_lock", None)
            if lock is not None:
                with lock:
                    active = set(getattr(self, "_async_route_active", set()) or set())
                dropped = ids.intersection(active)
                ids -= active
                if dropped:
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【检索治理】%s：%s 个正在执行的订阅已合并本次重复触发，不生成补偿轮",
                        str(trigger or "自动触发"),
                        len(dropped),
                    )
        if ids:
            return super()._queue_async_route_check(ids, trigger=trigger)

    # ------------------------------------------------------------------
    # 外部检索冷却：一轮允许迅雷 + Magnet/ED2K 共用，下一自动轮进入冷却
    # ------------------------------------------------------------------
    def _external_search_state_v1114(self) -> Dict[str, Any]:
        state = self.get_data("external_search_guard") or {}
        return state if isinstance(state, dict) else {}

    def _claim_external_search_round_v1114(self, subscribe: Any, force: bool = False) -> bool:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid <= 0:
            return False
        if force:
            self._external_round_allowed_v1114[sid] = True
            return True
        state = self._external_search_state_v1114()
        row = dict(state.get(str(sid)) or {})
        try:
            last_at = float(row.get("last_at") or 0)
        except (TypeError, ValueError):
            last_at = 0.0
        cooldown = max(900, int(self._external_search_cooldown_minutes_v1114) * 60)
        now = time.time()
        allowed = not last_at or now - last_at >= cooldown
        self._external_round_allowed_v1114[sid] = allowed
        if allowed:
            state[str(sid)] = {
                "last_at": now,
                "last_time": self._now_text(),
                "cooldown_minutes": int(self._external_search_cooldown_minutes_v1114),
            }
            if len(state) > 1000:
                ordered = sorted(
                    state.items(),
                    key=lambda pair: float((pair[1] or {}).get("last_at") or 0),
                    reverse=True,
                )[:1000]
                state = dict(ordered)
            self.save_data("external_search_guard", state)
        else:
            remaining = max(1, int((cooldown - (now - last_at)) / 60))
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【检索治理】#%s %s 外部观影检索仍在冷却，约 %s 分钟后才允许下一次自动检索",
                sid,
                str(getattr(subscribe, "name", "") or ""),
                remaining,
            )
        return allowed

    def _try_transfer_subscription(
        self,
        subscribe: Any,
        force: bool = False,
        refresh_channel: bool = True,
    ) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        # 已无缺集时先走完成闭环，绝不能为了确认状态继续访问观影/迅雷。
        if sid and not self._is_movie_subscription(subscribe):
            missing = list(self._subscription_missing_episodes(subscribe) or [])
            if not missing:
                completed = bool(self._finish_subscription_if_complete(subscribe))
                if completed:
                    return {
                        "success": True,
                        "handled": True,
                        "completed": True,
                        "message": "目标剧集已齐全，已完成订阅；未继续访问外部资源站",
                    }
        self._claim_external_search_round_v1114(subscribe, force=bool(force))
        try:
            return super()._try_transfer_subscription(
                subscribe,
                force=force,
                refresh_channel=refresh_channel,
            )
        finally:
            self._external_round_allowed_v1114.pop(sid, None)

    def _external_round_ok_v1114(self, subscribe: Any) -> bool:
        sid = int(getattr(subscribe, "id", 0) or 0)
        return bool(self._external_round_allowed_v1114.get(sid, True))

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not self._is_movie_subscription(subscribe):
            missing = list(self._subscription_missing_episodes(subscribe) or [])
            if not missing:
                completed = bool(self._finish_subscription_if_complete(subscribe))
                return {
                    "success": completed,
                    "handled": completed,
                    "shares": 0,
                    "attempted_files": 0,
                    "successful_files": 0,
                    "episodes": [],
                    "message": "订阅已无缺集，跳过迅雷外部检索" if not completed else "订阅已完成，跳过迅雷外部检索",
                }
        if not self._external_round_ok_v1114(subscribe):
            return {
                "success": False,
                "handled": False,
                "shares": 0,
                "attempted_files": 0,
                "successful_files": 0,
                "episodes": [],
                "cooldown": True,
                "message": "迅雷外部检索处于冷却期，本轮不访问观影/迅雷接口",
            }
        result = dict(super()._dispatch_xunlei_flash(subscribe) or {})
        if result.get("success") or result.get("episodes"):
            if self._finish_subscription_if_complete(subscribe):
                result["subscription_completed"] = True
                result["handled"] = True
        return result

    def _dispatch_viewing_external_v1113(self, subscribe: Any) -> Dict[str, Any]:
        if not self._external_round_ok_v1114(subscribe):
            return {
                "success": False,
                "actions": [],
                "cooldown": True,
                "message": "观影 Magnet/ED2K 外部检索处于冷却期，本轮不访问资源站",
            }
        return super()._dispatch_viewing_external_v1113(subscribe)

    # ------------------------------------------------------------------
    # 完成闭环：cloudcollection 完成后主动触发 MoviePilot 完成订阅
    # ------------------------------------------------------------------
    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(super()._poll_offline_source(source) or {})
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if str(data.get("state") or "") != "completed":
            return result
        source_id = str(source.get("id") or data.get("id") or "")
        latest = dict((self._source_store().get("items") or {}).get(source_id) or data or source)
        sid = int(latest.get("subscribe_id") or 0)
        subscribe = self._find_subscription(sid) if sid else None
        if subscribe:
            try:
                self._sync_media_facts_progress(subscribe)
            except Exception:
                pass
            if self._finish_subscription_if_complete(subscribe):
                result["subscription_completed"] = True
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【完成闭环】#%s %s 云添加完成后已触发 MoviePilot 订阅完成流程",
                    sid,
                    str(getattr(subscribe, "name", "") or ""),
                )
        return result

    # ------------------------------------------------------------------
    # 质量门禁
    # ------------------------------------------------------------------
    def _custom_reject_terms_v1114(self) -> List[str]:
        raw = str(self._quality_custom_reject_v1114 or "")
        return [
            token.strip().lower()
            for token in re.split(r"[\n,，;；]+", raw)
            if token.strip()
        ]

    def _quality_reject_reason_v1114(self, name: Any, size: Any = 0) -> str:
        text = str(name or "").strip()
        lower = text.lower()
        if _POISON_MEDIA_RE_V1114.search(text):
            return "广告/资源站伪视频"
        for token in self._custom_reject_terms_v1114():
            if token in lower:
                return f"命中自定义排除词 {token}"
        stem = str(Path(text).with_suffix("")) if text else ""
        if self._quality_reject_low_tags_v1114 and _LOW_QUALITY_RE_V1114.search(stem):
            return "命中 CAM/TS/TC/SCR 等低质量标签"
        resolutions = [int(value) for value in _RESOLUTION_RE_V1114.findall(text)]
        if resolutions and self._quality_min_resolution_v1114 > 0:
            if max(resolutions) < self._quality_min_resolution_v1114:
                return f"显式分辨率低于 {self._quality_min_resolution_v1114}p"
        try:
            bytes_size = int(size or 0)
        except (TypeError, ValueError):
            bytes_size = 0
        if self._quality_min_video_mb_v1114 > 0 and bytes_size > 0:
            if bytes_size < int(self._quality_min_video_mb_v1114) * 1024 * 1024:
                return f"视频小于 {self._quality_min_video_mb_v1114}MB"
        return ""

    @staticmethod
    def _subfile_name_v1114(row: Dict[str, Any]) -> str:
        return str(
            row.get("fileName")
            or row.get("name")
            or row.get("path")
            or row.get("file_name")
            or ""
        )

    @staticmethod
    def _subfile_size_v1114(row: Dict[str, Any]) -> int:
        try:
            return int(row.get("fileSize") or row.get("size") or row.get("file_size") or 0)
        except (TypeError, ValueError):
            return 0

    def _planner_file_selection(
        self,
        source: Dict[str, Any],
        subscribe: Any,
        resolved: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = dict(super()._planner_file_selection(source, subscribe, resolved) or {})
        if bool(result.get("ambiguous")):
            return result
        bt_info = resolved.get("btResInfo") if isinstance(resolved, dict) else None
        subfiles = bt_info.get("subfiles") if isinstance(bt_info, dict) else None
        if not isinstance(subfiles, list) or not subfiles:
            return result

        original_indexes = [int(value) for value in (result.get("indexes") or [])]
        if not original_indexes:
            return result
        kept_videos: List[int] = []
        kept_subtitles: List[int] = []
        rejected: List[str] = []
        season_hint = getattr(subscribe, "season", None)
        threshold = float(getattr(self, "_episode_auto_confidence", AUTO_SELECT_CONFIDENCE) or AUTO_SELECT_CONFIDENCE)

        for index in original_indexes:
            if index < 0 or index >= len(subfiles) or not isinstance(subfiles[index], dict):
                continue
            row = subfiles[index]
            name = self._subfile_name_v1114(row)
            if _is_video(name):
                reason = self._quality_reject_reason_v1114(name, self._subfile_size_v1114(row))
                if reason:
                    rejected.append(f"{name}: {reason}")
                    continue
                kept_videos.append(index)
            elif _is_subtitle(name):
                kept_subtitles.append(index)

        if not kept_videos and any(
            0 <= index < len(subfiles)
            and isinstance(subfiles[index], dict)
            and _is_video(self._subfile_name_v1114(subfiles[index]))
            for index in original_indexes
        ):
            return {
                **result,
                "indexes": [],
                "episodes": [],
                "ambiguous": True,
                "message": "资源视频全部被质量门禁过滤：" + "；".join(rejected[:6]),
                "quality_rejected": rejected[:30],
            }

        covered: set[int] = set()
        video_eps: Dict[int, set[int]] = {}
        for index in kept_videos:
            name = self._subfile_name_v1114(subfiles[index])
            eps = reliable_episode_set(
                resolve_episode(name, season_hint=season_hint),
                threshold,
            )
            video_eps[index] = set(eps)
            covered.update(eps)

        # 字幕强制策略只在用户显式开启时生效；否则保留父层已匹配到的字幕。
        if self._quality_require_subtitle_v1114 and kept_videos:
            subtitle_eps: set[int] = set()
            subtitle_parents = set()
            for index in kept_subtitles:
                name = self._subfile_name_v1114(subfiles[index])
                subtitle_parents.add(str(Path(name).parent).lower())
                subtitle_eps.update(
                    reliable_episode_set(resolve_episode(name, season_hint=season_hint), threshold)
                )
            subtitle_safe_videos: List[int] = []
            for index in kept_videos:
                name = self._subfile_name_v1114(subfiles[index])
                eps = video_eps.get(index) or set()
                has_signal = bool(_SUBTITLE_SIGNAL_RE_V1114.search(name))
                same_parent = str(Path(name).parent).lower() in subtitle_parents
                if has_signal or same_parent or bool(eps.intersection(subtitle_eps)):
                    subtitle_safe_videos.append(index)
                else:
                    rejected.append(f"{name}: 未检测到字幕信号")
            kept_videos = subtitle_safe_videos
            covered = set()
            for index in kept_videos:
                covered.update(video_eps.get(index) or set())
            if not kept_videos:
                return {
                    **result,
                    "indexes": [],
                    "episodes": [],
                    "ambiguous": True,
                    "message": "已开启字幕要求，但候选视频未检测到外部字幕或字幕标记",
                    "quality_rejected": rejected[:30],
                }

        # 只保留与最终视频同目录/同集的字幕，避免过滤视频后留下孤儿字幕。
        final_subtitles: List[int] = []
        video_parents = {
            str(Path(self._subfile_name_v1114(subfiles[index])).parent).lower()
            for index in kept_videos
        }
        for index in kept_subtitles:
            name = self._subfile_name_v1114(subfiles[index])
            eps = reliable_episode_set(resolve_episode(name, season_hint=season_hint), threshold)
            if eps.intersection(covered) or str(Path(name).parent).lower() in video_parents:
                final_subtitles.append(index)

        if rejected:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【质量过滤】%s：过滤 %s 个候选文件；%s",
                str(getattr(subscribe, "name", "") or ""),
                len(rejected),
                "；".join(rejected[:4]),
            )
        return {
            **result,
            "indexes": list(dict.fromkeys([*kept_videos, *final_subtitles])),
            "episodes": sorted(covered) if covered else list(result.get("episodes") or []),
            "quality_rejected": rejected[:30],
        }

    def _viewing_external_candidates_v1113(self, subscribe: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        rows, meta = super()._viewing_external_candidates_v1113(subscribe)
        kept = []
        rejected = []
        for row in rows:
            descriptor = str(row.get("name") or row.get("search_title") or "")
            reason = self._quality_reject_reason_v1114(descriptor, 0)
            if reason:
                rejected.append(f"{descriptor}: {reason}")
                continue
            kept.append(row)
        if rejected:
            meta = dict(meta or {})
            meta["quality_filtered"] = len(rejected)
            meta["quality_rejected"] = rejected[:20]
        return kept, meta

    # ------------------------------------------------------------------
    # 配置 UI
    # ------------------------------------------------------------------
    def get_form(self):
        form, defaults = super().get_form()
        try:
            content = form[0].get("content") if form else None
            if isinstance(content, list):
                content.append({
                    "component": "VCard",
                    "props": {"variant": "tonal", "class": "mt-3"},
                    "content": [
                        {"component": "VCardTitle", "text": "外部检索与质量门禁"},
                        {
                            "component": "VCardText",
                            "text": (
                                "自动观影/迅雷检索按订阅冷却，执行中的周期触发会被合并，不再连续补偿轮询。"
                                "质量门禁默认过滤 BPHDTV 广告伪视频、CAM/TC/SCR 与显式低于 720p 的资源；"
                                "字幕要求默认关闭，可按需要开启。"
                            ),
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 4},
                                    "content": [{"component": "VTextField", "props": {
                                        "model": "external_search_cooldown_minutes",
                                        "label": "同订阅外部检索冷却（分钟）",
                                        "type": "number", "min": "15", "max": "1440",
                                    }}],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 4},
                                    "content": [{"component": "VTextField", "props": {
                                        "model": "quality_min_resolution",
                                        "label": "最低显式分辨率（p）",
                                        "type": "number", "min": "0", "max": "4320",
                                    }}],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 4},
                                    "content": [{"component": "VTextField", "props": {
                                        "model": "quality_min_video_mb",
                                        "label": "最小视频大小（MB，0关闭）",
                                        "type": "number", "min": "0", "max": "10000",
                                    }}],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 6},
                                    "content": [{"component": "VSwitch", "props": {
                                        "model": "quality_reject_low_tags",
                                        "label": "过滤 CAM/TS/TC/SCR 等低质标签",
                                    }}],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 6},
                                    "content": [{"component": "VSwitch", "props": {
                                        "model": "quality_require_subtitle",
                                        "label": "要求字幕信号（外部字幕/中字/CHS/内封等）",
                                    }}],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [{"component": "VTextarea", "props": {
                                        "model": "quality_custom_reject",
                                        "label": "自定义排除词（逗号或换行分隔）",
                                        "rows": 2,
                                        "placeholder": "例如：某资源站.com, 水印组名",
                                    }}],
                                },
                            ],
                        },
                    ],
                })
        except Exception:
            pass
        defaults.update({
            "external_search_cooldown_minutes": self._external_search_cooldown_minutes_v1114,
            "quality_min_resolution": self._quality_min_resolution_v1114,
            "quality_min_video_mb": self._quality_min_video_mb_v1114,
            "quality_reject_low_tags": self._quality_reject_low_tags_v1114,
            "quality_require_subtitle": self._quality_require_subtitle_v1114,
            "quality_custom_reject": self._quality_custom_reject_v1114,
        })
        return form, defaults


__all__ = ["GuangYaGovernanceV1114Mixin"]
