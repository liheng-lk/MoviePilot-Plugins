"""v1.10.13 运行时收口：迅雷 captcha 自愈与外部获取成功通知。

修复两个真实运行问题：
- 迅雷匿名分享接口返回“验证码无效”等中文错误时，旧逻辑没有识别为 captcha 失效；
  并且只有配置了 captcha/init JSON 才会重试，导致一批候选连续失败。现在首次失效会
  清空运行时 token，调用既有 signed-init / configured-init 刷新一次并重试，同批后续
  请求复用新的 client/device/token 组合。
- 光鸭直接转存已有成功通知，但迅雷秒传与 Magnet/ED2K cloudcollection 完成没有通知。
  本层只对“本次新完成”发送一次插件通知，历史 completed 状态不会重复推送。

不会记录 captcha_token、Device ID、磁力 URI 或其它密钥。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from app.schemas.types import NotificationType

from .xunlei_flash_v193 import XUNLEI_API_BASE


_CAPTCHA_INVALID_RE_V1113 = re.compile(
    r"captcha|captcha[_ -]?token|验证码(?:无效|失效|错误|过期)?|"
    r"验证(?:码)?(?:无效|失效|错误|过期)|device.*match|device[_ -]?id.*empty",
    re.I,
)


class GuangYaRuntimeFixV1113Mixin:
    """最终运行时修复层；放在完整插件 MRO 最外侧。"""

    build_id = "20260902-r24"

    @staticmethod
    def _xunlei_captcha_invalid_v1113(response: Any, payload: Any) -> bool:
        """识别迅雷 captcha 失效，兼容中文错误和少数 HTTP 200 错误包。"""
        fields = []
        has_error_field = False
        if isinstance(payload, dict):
            for key in ("error", "error_description", "message", "msg"):
                value = payload.get(key)
                if value not in (None, ""):
                    fields.append(str(value))
                    if key in {"error", "error_description"}:
                        has_error_field = True
        text = " ".join(fields).strip()
        if not text:
            text = str(getattr(response, "text", "") or "")[:1200]
        try:
            status = int(getattr(response, "status_code", 0) or 0)
        except (TypeError, ValueError):
            status = 0
        invalid_hint = bool(_CAPTCHA_INVALID_RE_V1113.search(text))
        return invalid_hint and (status >= 400 or has_error_field)

    def _xunlei_get(self, endpoint: str, params: Dict[str, Any], *, action: str) -> Dict[str, Any]:
        """迅雷 GET：captcha 失效时无条件尝试一次既有刷新能力，不要求 init JSON。"""
        session = self._xunlei_session()
        url = f"{XUNLEI_API_BASE}{endpoint}"
        last_error = ""
        for attempt in range(2):
            headers = self._xunlei_headers(action, refresh=False)
            if not headers.get("x-captcha-token"):
                raise RuntimeError(
                    "迅雷 captcha_token 不可用；自动初始化未取得有效 token"
                )
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=int(getattr(self, "_provider_timeout", 15) or 15),
            )
            try:
                payload = response.json()
            except Exception:
                payload = {}

            captcha_invalid = self._xunlei_captcha_invalid_v1113(response, payload)
            if int(getattr(response, "status_code", 0) or 0) < 400 and not captcha_invalid:
                return payload if isinstance(payload, dict) else {}

            last_error = str(
                (payload or {}).get("error_description")
                or (payload or {}).get("error")
                or (payload or {}).get("message")
                or (payload or {}).get("msg")
                or getattr(response, "text", "")
                or f"HTTP {getattr(response, 'status_code', 0)}"
            )[:300]

            if attempt == 0 and captcha_invalid:
                self._xunlei_runtime_captcha_token = ""
                refreshed = str(self._refresh_xunlei_captcha(action) or "").strip()
                if refreshed:
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【迅雷秒传】检测到 captcha 失效，已自动刷新运行时验证并重试当前分享",
                    )
                    continue
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【迅雷秒传】检测到 captcha 失效，但自动刷新未取得新 token；继续回退后续来源",
                )
            break
        raise RuntimeError(f"迅雷分享接口失败：{last_error or 'unknown error'}")

    def _notify_acquisition_v1113(self, title: str, lines: Iterable[str]) -> bool:
        text = "\n".join(str(line or "").strip() for line in lines if str(line or "").strip())
        try:
            self.post_message(
                mtype=NotificationType.Plugin,
                title=str(title or "光鸭转存助手"),
                text=text,
            )
            return True
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【通知】外部获取成功通知发送失败：%s",
                str(err)[:240],
            )
            return False

    @staticmethod
    def _episode_text_v1113(values: Iterable[Any]) -> str:
        episodes = []
        for raw in values or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in episodes:
                episodes.append(value)
        return ", ".join(f"E{value:02d}" for value in sorted(episodes))

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        """仅通知本次新完成的迅雷秒传文件，历史 completed 不重复推送。"""
        sid = int(getattr(subscribe, "id", 0) or 0)
        before_state = self._xunlei_state()
        before_items = dict(before_state.get("items") or {}) if isinstance(before_state, dict) else {}
        before_completed = {
            key
            for key, row in before_items.items()
            if isinstance(row, dict)
            and int(row.get("subscribe_id") or 0) == sid
            and str(row.get("state") or "") == "completed"
        }

        result = dict(super()._dispatch_xunlei_flash(subscribe) or {})

        after_state = self._xunlei_state()
        after_items = dict(after_state.get("items") or {}) if isinstance(after_state, dict) else {}
        new_rows = [
            row
            for key, row in after_items.items()
            if key not in before_completed
            and isinstance(row, dict)
            and int(row.get("subscribe_id") or 0) == sid
            and str(row.get("state") or "") == "completed"
        ]
        if new_rows:
            episodes = set()
            for row in new_rows:
                for raw in row.get("episodes") or []:
                    try:
                        value = int(raw)
                    except (TypeError, ValueError):
                        continue
                    if value > 0:
                        episodes.add(value)
            name = str(getattr(subscribe, "name", "") or "未知媒体")
            year = str(getattr(subscribe, "year", "") or "").strip()
            season = getattr(subscribe, "season", None)
            identity = " ".join(
                value
                for value in (
                    name,
                    f"({year})" if year else "",
                    f"S{int(season):02d}" if season not in (None, "") else "",
                )
                if value
            )
            episode_text = self._episode_text_v1113(episodes)
            lines = [
                f"媒体：{identity}",
                "来源：观影迅雷分享 → 光鸭秒传",
                f"本次成功：{len(new_rows)} 个文件",
            ]
            if episode_text:
                lines.append(f"覆盖集数：{episode_text}")
            if self._notify_acquisition_v1113("⚡ 光鸭秒传成功", lines):
                self._plugin_log(
                    "INFO",
                    "【光鸭转存助手】【通知】已发送迅雷秒传成功通知：#%s %s files=%s episodes=%s",
                    sid,
                    name,
                    len(new_rows),
                    episode_text or "-",
                )
        return result

    def _notify_cloud_completed_v1113(self, source: Dict[str, Any], result: Dict[str, Any]) -> None:
        source_id = str(source.get("id") or "")
        if not source_id:
            return
        current = dict((self._source_store().get("items") or {}).get(source_id) or source)
        data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}
        current = {**current, **data}
        if str(current.get("state") or "") != "completed":
            return
        if current.get("completion_notified_at"):
            return
        source_type = str(current.get("type") or "").lower()
        if source_type not in {"magnet", "ed2k"}:
            return

        sid = int(current.get("subscribe_id") or 0)
        subscribe = self._find_subscription(sid) if sid else None
        name = str(getattr(subscribe, "name", "") or current.get("search_title") or "未知媒体")
        year = str(getattr(subscribe, "year", "") or "").strip() if subscribe else ""
        season = getattr(subscribe, "season", None) if subscribe else None
        identity = " ".join(
            value
            for value in (
                name,
                f"({year})" if year else "",
                f"S{int(season):02d}" if season not in (None, "") else "",
            )
            if value
        )
        episodes = current.get("resolved_episodes") or current.get("target_episodes") or []
        episode_text = self._episode_text_v1113(episodes)
        resolved_name = str(
            current.get("renamed_name")
            or current.get("requested_name")
            or current.get("resolved_name")
            or current.get("label")
            or ""
        ).strip()
        task_id = str(current.get("task_id") or "").strip()
        lines = [
            f"媒体：{identity}",
            f"来源：{source_type.upper()} → 光鸭原生云添加",
        ]
        if episode_text:
            lines.append(f"覆盖集数：{episode_text}")
        if resolved_name:
            lines.append(f"文件：{resolved_name[:180]}")
        if task_id:
            lines.append(f"任务：{task_id[:90]}")

        if self._notify_acquisition_v1113("☁️ 光鸭云添加完成", lines):
            self._update_source(source_id, completion_notified_at=self._now_text())
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【通知】已发送云添加完成通知：source=%s type=%s subscribe=%s episodes=%s",
                source_id,
                source_type.upper(),
                sid,
                episode_text or "movie/auto",
            )

    def _submit_offline_source(self, source_id: str) -> Dict[str, Any]:
        before = dict((self._source_store().get("items") or {}).get(str(source_id or "")) or {})
        result = dict(super()._submit_offline_source(source_id) or {})
        self._notify_cloud_completed_v1113(before or {"id": source_id}, result)
        return result

    def _poll_offline_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(super()._poll_offline_source(source) or {})
        self._notify_cloud_completed_v1113(dict(source or {}), result)
        return result


__all__ = ["GuangYaRuntimeFixV1113Mixin"]
