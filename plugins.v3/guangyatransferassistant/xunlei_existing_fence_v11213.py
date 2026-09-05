"""v1.12.13 迅雷秒传“已入库集绝不再导入”最终物理栅栏。

实机发现：MoviePilot 媒体库已经存在 E01-E09，频道刚补 E10 后，人工完整检查中的
迅雷秒传仍可能把 E01-E06 送入 JSON import。底层虽然在迅雷规划前调用
``_sync_media_library_progress``，但旧实现丢弃同步返回的 ``missing``，随后重新经过多层
``_subscription_missing_episodes`` 包装计算目标；一旦运行态 scope/旧 note/缓存事实有漂移，
全量迅雷包就可能重新包含已入库集。

本层把安全边界收紧为三道硬门：
1. TV 迅雷开始前必须成功读取 MoviePilot 媒体库缺集事实；同步失败则只跳过迅雷并回退
   光鸭分享/Magnet/ED2K，不用“不确定”状态冒险秒传整包；
2. 迅雷允许集 = 媒体库 missing ∩ 当前订阅/成功事实 missing - reservation - active claim；
3. 真正调用 JSON batch importer 前再次逐视频解析集号，视频集号必须完整属于当前允许集。
   E09-E11 这类横跨“已有+缺失”的多集文件会整文件拒绝，不允许为了 E11 顺带重复 E09/E10。

本层不修改迅雷协议、JSON 1.1.3、来源优先级或 MoviePilot 完成规则。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin
from .legacy import _is_subtitle, _is_video


class GuangYaXunleiExistingEpisodeFenceV11213Mixin(GuangYaGyingAliasQueryV11212Mixin):
    """让 MoviePilot 媒体库事实成为迅雷 JSON 导入不可越过的上界。"""

    plugin_version = "1.12.13"
    build_id = "20260905-r59"

    def init_plugin(self, config: dict = None) -> None:
        self._xunlei_existing_fence_local_v11213 = threading.local()
        return super().init_plugin(config)

    @staticmethod
    def _positive_set_v11213(values: Iterable[Any]) -> Set[int]:
        result: Set[int] = set()
        for raw in values or []:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return result

    def _xunlei_fence_local_v11213(self) -> threading.local:
        local = getattr(self, "_xunlei_existing_fence_local_v11213", None)
        if local is None:
            local = threading.local()
            self._xunlei_existing_fence_local_v11213 = local
        return local

    @contextmanager
    def _xunlei_fence_scope_v11213(
        self,
        subscribe: Any,
        allowed: Iterable[int],
        library_existing: Iterable[int],
    ) -> Iterator[None]:
        local = self._xunlei_fence_local_v11213()
        previous = getattr(local, "scope", None)
        had_previous = hasattr(local, "scope")
        local.scope = {
            "subscribe_id": int(getattr(subscribe, "id", 0) or 0),
            "allowed": sorted(self._positive_set_v11213(allowed)),
            "library_existing": sorted(self._positive_set_v11213(library_existing)),
        }
        try:
            yield
        finally:
            if had_previous:
                local.scope = previous
            else:
                try:
                    delattr(local, "scope")
                except AttributeError:
                    pass

    def _xunlei_fence_scope_value_v11213(self, subscribe: Any) -> Optional[Dict[str, Any]]:
        local = getattr(self, "_xunlei_existing_fence_local_v11213", None)
        scope = getattr(local, "scope", None) if local is not None else None
        if not isinstance(scope, dict):
            return None
        sid = int(getattr(subscribe, "id", 0) or 0)
        if sid <= 0 or sid != int(scope.get("subscribe_id") or 0):
            return None
        return dict(scope)

    def _base_missing_without_due_scope_v11213(self, subscribe: Any) -> Set[int]:
        """读取成功事实/订阅 note 的真实缺集，同时明确绕开日历 due scope。"""
        without_scope = getattr(self, "_without_due_scope_v1120", None)
        if callable(without_scope):
            with without_scope():
                values = super()._subscription_missing_episodes(subscribe) or []
        else:
            values = super()._subscription_missing_episodes(subscribe) or []
        return self._positive_set_v11213(values)

    def _xunlei_authoritative_missing_v11213(
        self,
        subscribe: Any,
    ) -> Tuple[Optional[Set[int]], Dict[str, Any]]:
        """返回迅雷可处理的硬缺集；None 表示媒体库事实读取失败，必须 fail closed。"""
        try:
            sync = dict(self._sync_media_library_progress(subscribe) or {})
        except Exception as err:
            sync = {"success": False, "existing": [], "missing": [], "message": str(err)[:260]}
        if not bool(sync.get("success")):
            return None, sync

        library_missing = self._positive_set_v11213(sync.get("missing") or [])
        logical_missing = self._base_missing_without_due_scope_v11213(subscribe)
        allowed = library_missing.intersection(logical_missing)

        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            allowed -= self._positive_set_v11213(reservations.get("episodes") or [])
        except Exception:
            pass
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            claims = self._active_source_claims(sid) if sid > 0 else []
            allowed -= self._positive_set_v11213(claims or [])
        except Exception:
            pass
        return allowed, sync

    def _subscription_missing_episodes(self, subscribe: Any) -> List[int]:
        """仅在迅雷物理栅栏作用域内，把所有下层缺集计算再与硬白名单求交集。"""
        values = self._positive_set_v11213(super()._subscription_missing_episodes(subscribe) or [])
        scope = self._xunlei_fence_scope_value_v11213(subscribe)
        if not scope:
            return sorted(values)
        allowed = self._positive_set_v11213(scope.get("allowed") or [])
        return sorted(values.intersection(allowed))

    @staticmethod
    def _xunlei_parent_v11213(value: Any) -> str:
        path = str(value or "").replace("\\", "/")
        return path.rsplit("/", 1)[0].casefold() if "/" in path else ""

    def _xunlei_current_fence_allowed_v11213(self, subscribe: Any) -> Optional[Set[int]]:
        scope = self._xunlei_fence_scope_value_v11213(subscribe)
        if not scope:
            return None
        # 不再次访问媒体库网络/数据库链；初始 library missing 是不可放宽的上界，
        # 提交前只允许被新的成功事实/reservation/claim 继续缩小。
        allowed = self._positive_set_v11213(scope.get("allowed") or [])
        allowed &= self._base_missing_without_due_scope_v11213(subscribe)
        try:
            reservations = dict(self._pending_reservations(subscribe) or {})
            allowed -= self._positive_set_v11213(reservations.get("episodes") or [])
        except Exception:
            pass
        sid = int(getattr(subscribe, "id", 0) or 0)
        try:
            allowed -= self._positive_set_v11213(self._active_source_claims(sid) or [])
        except Exception:
            pass
        return allowed

    def _filter_xunlei_import_indexes_v11213(
        self,
        subscribe: Any,
        rows: List[Dict[str, Any]],
        include_indexes: Iterable[int],
        allowed: Set[int],
    ) -> Tuple[Set[int], Set[int]]:
        """JSON 最后一跳：任何视频只要包含一个非当前缺集，就不允许导入。"""
        included = {
            int(value) for value in (include_indexes or [])
            if str(value).lstrip("-").isdigit() and 0 <= int(value) < len(rows)
        }
        if not included or not allowed:
            return set(), set(included)

        package_paths = [
            str(rows[index].get("path") or rows[index].get("name") or "")
            for index in sorted(included)
            if _is_video(str(rows[index].get("path") or rows[index].get("name") or ""))
            or _is_subtitle(str(rows[index].get("path") or rows[index].get("name") or ""))
        ]
        keep: Set[int] = set()
        blocked: Set[int] = set()
        allowed_video_eps: Set[int] = set()
        videos_by_parent: Dict[str, List[int]] = {}

        # 视频先判定。必须能高置信解析，而且解析到的全部集号都仍在硬缺集白名单内。
        for index in sorted(included):
            row = rows[index]
            path = str(row.get("path") or row.get("name") or "")
            if not _is_video(path):
                continue
            episodes = self._positive_set_v11213(
                self._xunlei_file_episodes(subscribe, row, package_paths=package_paths) or []
            )
            if episodes and episodes.issubset(allowed):
                keep.add(index)
                allowed_video_eps.update(episodes)
                videos_by_parent.setdefault(self._xunlei_parent_v11213(path), []).append(index)
            else:
                blocked.add(index)

        # 字幕只能跟随已经通过硬栅栏的视频；有明确集号时也必须完整属于这些视频的集号。
        for index in sorted(included):
            row = rows[index]
            path = str(row.get("path") or row.get("name") or "")
            if not _is_subtitle(path):
                continue
            episodes = self._positive_set_v11213(
                self._xunlei_file_episodes(subscribe, row, package_paths=package_paths) or []
            )
            if episodes:
                if episodes.issubset(allowed_video_eps):
                    keep.add(index)
                else:
                    blocked.add(index)
                continue
            parent = self._xunlei_parent_v11213(path)
            if len(videos_by_parent.get(parent) or []) == 1:
                keep.add(index)
            else:
                blocked.add(index)

        # planner 不应把其它文件类型送入 include；出现时一律 fail closed。
        blocked.update(included - keep)
        return keep, blocked

    def _xunlei_import_json_batch_v1123(
        self,
        subscribe: Any,
        template: Dict[str, Any],
        source_rows: Iterable[Dict[str, Any]],
        skip_indexes: Optional[Iterable[int]] = None,
        include_indexes: Optional[Iterable[int]] = None,
    ) -> Dict[str, Any]:
        if self._is_movie_subscription(subscribe):
            return super()._xunlei_import_json_batch_v1123(
                subscribe, template, source_rows,
                skip_indexes=skip_indexes, include_indexes=include_indexes,
            )
        scope = self._xunlei_fence_scope_value_v11213(subscribe)
        if not scope:
            return super()._xunlei_import_json_batch_v1123(
                subscribe, template, source_rows,
                skip_indexes=skip_indexes, include_indexes=include_indexes,
            )

        rows = [dict(row or {}) for row in source_rows]
        original = (
            {int(value) for value in include_indexes}
            if include_indexes is not None
            else set(range(len(rows)))
        )
        current_allowed = self._xunlei_current_fence_allowed_v11213(subscribe) or set()
        filtered, blocked = self._filter_xunlei_import_indexes_v11213(
            subscribe, rows, original, current_allowed,
        )
        if blocked:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷已入库硬栅栏v1.12.13】#%s JSON 提交前拦截 %s/%s 个文件；当前允许缺集=%s",
                int(getattr(subscribe, "id", 0) or 0),
                len(blocked), len(original),
                ",".join(f"E{value:02d}" for value in sorted(current_allowed)) or "无",
            )
        if not filtered:
            return {
                "success": False,
                "results": [],
                "message": "迅雷 JSON 最终硬栅栏：没有仍属于当前真实缺集的文件，已阻止重复秒传",
                "fence_blocked_v11213": len(blocked),
            }
        result = dict(super()._xunlei_import_json_batch_v1123(
            subscribe,
            template,
            rows,
            skip_indexes=skip_indexes,
            include_indexes=sorted(filtered),
        ) or {})
        result["fence_blocked_v11213"] = len(blocked)
        result["fence_allowed_episodes_v11213"] = sorted(current_allowed)
        return result

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        if self._is_movie_subscription(subscribe):
            return super()._dispatch_xunlei_flash(subscribe)

        allowed, sync = self._xunlei_authoritative_missing_v11213(subscribe)
        sid = int(getattr(subscribe, "id", 0) or 0)
        if allowed is None:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷已入库硬栅栏v1.12.13】#%s MoviePilot 媒体库缺集事实读取失败；本轮禁用迅雷秒传，继续后续来源",
                sid,
            )
            return {
                "success": False,
                "handled": False,
                "priority": 0,
                "shares": 0,
                "attempted_files": 0,
                "successful_files": 0,
                "episodes": [],
                "errors": [str(sync.get("message") or "媒体库同步失败")[:260]],
                "message": "MoviePilot 媒体库缺集事实读取失败；为避免重复集，本轮跳过迅雷秒传",
                "fence_fail_closed_v11213": True,
            }

        existing = self._positive_set_v11213(sync.get("existing") or [])
        self._plugin_log(
            "INFO",
            "【光鸭转存助手】【迅雷已入库硬栅栏v1.12.13】#%s 媒体库已有=%s；迅雷最终允许=%s",
            sid,
            ",".join(f"E{value:02d}" for value in sorted(existing)) or "无",
            ",".join(f"E{value:02d}" for value in sorted(allowed)) or "无",
        )
        if not allowed:
            return {
                "success": False,
                "handled": False,
                "priority": 0,
                "shares": 0,
                "attempted_files": 0,
                "successful_files": 0,
                "episodes": [],
                "errors": [],
                "message": "迅雷硬栅栏确认当前没有可安全秒传的真实缺集",
                "fence_allowed_v11213": [],
            }

        with self._xunlei_fence_scope_v11213(subscribe, allowed, existing):
            result = dict(super()._dispatch_xunlei_flash(subscribe) or {})
        leaked = self._positive_set_v11213(result.get("episodes") or []) - set(allowed)
        if leaked:
            # 理论上最终 importer 已不可能越过；保留显式异常诊断，绝不把越界集当成功回执上报。
            self._plugin_log(
                "ERROR",
                "【光鸭转存助手】【迅雷已入库硬栅栏v1.12.13】#%s 检测到越界回执=%s，已从成功回执剔除",
                sid,
                ",".join(f"E{value:02d}" for value in sorted(leaked)),
            )
            safe_episodes = self._positive_set_v11213(result.get("episodes") or []).intersection(allowed)
            result["episodes"] = sorted(safe_episodes)
            result["handled"] = False
            result["fence_leaked_receipts_v11213"] = sorted(leaked)
        result["fence_allowed_v11213"] = sorted(allowed)
        return result


__all__ = ["GuangYaXunleiExistingEpisodeFenceV11213Mixin"]
