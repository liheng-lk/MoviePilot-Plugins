"""v1.10.13 运行时收口：迅雷真实设备合同、captcha 熔断与外部获取成功通知。

本层处理真实运行中暴露的三个边界：
- 迅雷匿名分享请求对 device/client/captcha 绑定敏感。除 x-device-id/x-guid 外，
  api-pan.xunlei.com 请求同步补 device_id/did/guid query，与已验证可工作的浏览器脚本一致；
- captcha 失效最多刷新并重试一次；再次失败后本轮直接熔断，剩余候选只在本地跳过，
  避免一个坏 token 对迅雷分享接口形成连续请求；
- 光鸭直接转存已有成功通知，迅雷秒传与 Magnet/ED2K cloudcollection 完成也发送一次通知。

不会记录 captcha_token、Device ID、磁力 URI 或其它密钥。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from app.schemas.types import NotificationType

from .gying_fallback_reuse_v1113 import GuangYaGyingFallbackReuseV1113Mixin


_XUNLEI_API_BASE_V1113 = "https://api-pan.xunlei.com"
_CAPTCHA_INVALID_RE_V1113 = re.compile(
    r"captcha|captcha[_ -]?token|验证码(?:无效|失效|错误|过期)?|"
    r"验证(?:码)?(?:无效|失效|错误|过期)|device.*match|device[_ -]?id.*empty",
    re.I,
)


class GuangYaRuntimeFixV1113Mixin(GuangYaGyingFallbackReuseV1113Mixin):
    """观影 UI 链中的最终运行时修复层。"""

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
            details = payload.get("error_details")
            if isinstance(details, list):
                for row in details:
                    if isinstance(row, dict) and row.get("detail"):
                        fields.append(str(row.get("detail")))
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

    def _xunlei_device_params_v1113(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """按迅雷 Web 请求合同给 api-pan 请求同步补齐三个 device query。"""
        output = dict(params or {})
        device_id = str(
            getattr(self, "_xunlei_runtime_device_id", "")
            or getattr(self, "_xunlei_device_id", "")
            or ""
        ).strip()
        if device_id:
            output.setdefault("device_id", device_id)
            output.setdefault("did", device_id)
            output.setdefault("guid", device_id)
        return output

    def _xunlei_get(self, endpoint: str, params: Dict[str, Any], *, action: str) -> Dict[str, Any]:
        """迅雷 GET：真实设备 query + 一次 captcha 恢复 + 本轮熔断。"""
        if bool(getattr(self, "_xunlei_captcha_circuit_open_v1113", False)):
            raise RuntimeError("迅雷 captcha 本轮已熔断；已停止继续请求分享接口，等待下轮或更新真实 captcha/device")

        session = self._xunlei_session()
        url = f"{_XUNLEI_API_BASE_V1113}{endpoint}"
        request_params = self._xunlei_device_params_v1113(params)
        last_error = ""

        for attempt in range(2):
            headers = self._xunlei_headers(action, refresh=False)
            token_before = str(headers.get("x-captcha-token") or "").strip()
            if not token_before:
                self._xunlei_captcha_circuit_open_v1113 = True
                raise RuntimeError("迅雷 captcha_token 不可用；本轮已熔断分享接口")

            response = session.get(
                url,
                params=request_params,
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

            if attempt == 0 and captcha_invalid and not bool(
                getattr(self, "_xunlei_captcha_refresh_used_v1113", False)
            ):
                self._xunlei_captcha_refresh_used_v1113 = True
                self._xunlei_runtime_captcha_token = ""
                refreshed = str(self._refresh_xunlei_captcha(action) or "").strip()
                if refreshed and refreshed != token_before:
                    self._plugin_log(
                        "INFO",
                        "【光鸭转存助手】【迅雷秒传】检测到 captcha 失效，已刷新运行时验证并仅重试当前分享一次",
                    )
                    continue
                self._xunlei_captcha_circuit_open_v1113 = True
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【迅雷秒传】captcha 失效且未取得新的有效验证态；本轮已熔断迅雷分享接口，避免连续请求",
                )
                break

            if captcha_invalid:
                self._xunlei_captcha_circuit_open_v1113 = True
                self._plugin_log(
                    "WARNING",
                    "【光鸭转存助手】【迅雷秒传】captcha 重试仍无效；本轮已熔断迅雷分享接口，请更新真实 captcha_token + Device ID",
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
        """每轮重置 captcha 熔断；仅通知本次新完成的迅雷秒传文件。"""
        self._xunlei_captcha_circuit_open_v1113 = False
        self._xunlei_captcha_refresh_used_v1113 = False

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
        result["captcha_circuit_open"] = bool(
            getattr(self, "_xunlei_captcha_circuit_open_v1113", False)
        )

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
