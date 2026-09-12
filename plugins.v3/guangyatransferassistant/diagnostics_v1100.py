"""非破坏性运行健康诊断。

只检查资源来源/观影会话、固定订阅搜索前置条件与迅雷秒传预检。
不会搜索具体订阅资源，不创建光鸭文件、上传任务或 MoviePilot 下载任务；
公开结果不包含 Cookie、密码、token、captcha_token 等敏感值。
"""

from __future__ import annotations

from typing import Any, Dict, List


class GuangYaDiagnosticsV1100Mixin:
    """面向 UI 和人工排障的聚合诊断层。"""

    build_id = "20260901-r11"

    @staticmethod
    def _diag_row(key: str, name: str, ok: bool, message: str, *, skipped: bool = False, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "key": key,
            "name": name,
            "ok": bool(ok),
            "skipped": bool(skipped),
            "message": str(message or "")[:400],
        }
        if data:
            row["data"] = data
        return row

    @staticmethod
    def _diag_int(value: Any, default: int = 0) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    def api_full_diagnostics(self) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        issues: List[str] = []

        # 1) 资源来源：观影会话 + 外部 Magnet/ED2K API。
        try:
            provider_defs = list(self._parse_provider_defs())
            provider = dict(self.api_provider_test() or {})
            provider_states = list(provider.get("providers") or [])
            configured_external = bool(provider_defs)
            viewing_enabled = bool(getattr(self, "_viewing_enabled", False))
            required_states = [
                row for row in provider_states
                if not (
                    str(row.get("provider") or "") == "viewing" and not viewing_enabled
                )
            ]
            provider_ok = all(bool(row.get("success")) for row in required_states) if required_states else True
            if not provider_ok:
                bad = [str(row.get("provider") or "provider") for row in required_states if not row.get("success")]
                issues.append("资源来源不可用：" + "、".join(bad[:6]))
            checks.append(self._diag_row(
                "providers",
                "资源来源",
                provider_ok,
                str(provider.get("message") or ("检测通过" if provider_ok else "部分来源不可用")),
                skipped=not viewing_enabled and not configured_external,
                data={
                    "viewing_enabled": viewing_enabled,
                    "external_count": len(provider_defs),
                    "providers": [
                        {
                            "provider": str(row.get("provider") or ""),
                            "kind": str(row.get("kind") or ""),
                            "success": bool(row.get("success")),
                            "message": str(row.get("message") or "")[:240],
                            "node": str(row.get("node") or ""),
                            "query_param": str(row.get("query_param") or ""),
                        }
                        for row in provider_states[:20]
                    ],
                },
            ))
        except Exception as err:
            provider_ok = False
            issues.append("资源来源检测异常")
            checks.append(self._diag_row("providers", "资源来源", False, str(err)))

        # 2) 固定订阅搜索只检查“是否具备搜索条件”，不主动搜索具体媒体。
        # 具体搜索已经有 /providers/search/selected；健康诊断不能因为一次点击
        # 对全部固定订阅再次访问 GYING / 外部 Provider。
        selected: List[int] = []
        for value in (getattr(self, "_selected_subscriptions", []) or []):
            sid = self._diag_int(value, 0)
            if sid > 0 and sid not in selected:
                selected.append(sid)

        cached_search = self.get_data("provider_search_last") or {}
        if not isinstance(cached_search, dict):
            cached_search = {}
        if selected:
            search_ready = bool(provider_ok)
            cached_items = list(cached_search.get("items") or [])
            cached_matched = bool(cached_search.get("matched"))
            cached_complete = cached_search.get("search_complete")
            detail = (
                f"已选择 {len(selected)} 个固定转存订阅；来源健康检查"
                + ("通过" if search_ready else "未通过")
                + "。具体资源请使用“搜索缺失资源”。"
            )
            checks.append(self._diag_row(
                "selected_search_ready",
                "固定订阅搜索就绪",
                search_ready,
                detail,
                data={
                    "subscriptions": len(selected),
                    "cached_search_available": bool(cached_items or cached_search.get("updated_at")),
                    "cached_matched": cached_matched,
                    "cached_search_complete": cached_complete,
                    "cached_updated_at": str(cached_search.get("updated_at") or ""),
                },
            ))
            if not search_ready:
                issues.append("固定订阅搜索前置来源未就绪")
        else:
            checks.append(self._diag_row(
                "selected_search_ready",
                "固定订阅搜索就绪",
                True,
                "未选择固定走光鸭的 MoviePilot 订阅，跳过具体媒体搜索",
                skipped=True,
            ))

        # 3) 秒传链路：观影会话、迅雷匿名身份、光鸭 userres，均为非破坏性检查。
        if bool(getattr(self, "_xunlei_flash_enabled", True)):
            try:
                rapid = dict(self.api_xunlei_preflight() or {})
                rapid_ok = bool(rapid.get("rapid_ready"))
                stages = list(rapid.get("stages") or [])
                if not rapid_ok:
                    bad = [str(row.get("name") or row.get("key") or "阶段") for row in stages if not row.get("ok")]
                    issues.append("秒传链路未就绪：" + "、".join(bad[:6]))
                checks.append(self._diag_row(
                    "xunlei_rapid",
                    "迅雷秒传链路",
                    rapid_ok,
                    str(rapid.get("message") or "预检完成"),
                    data={
                        "stages": [
                            {
                                "key": str(row.get("key") or ""),
                                "name": str(row.get("name") or ""),
                                "ok": bool(row.get("ok")),
                                "message": str(row.get("message") or "")[:240],
                                "node": str(row.get("node") or ""),
                                "login_mode": str(row.get("login_mode") or ""),
                            }
                            for row in stages[:10]
                        ]
                    },
                ))
            except Exception as err:
                rapid_ok = False
                issues.append("迅雷秒传预检异常")
                checks.append(self._diag_row("xunlei_rapid", "迅雷秒传链路", False, str(err)))
        else:
            rapid_ok = True
            checks.append(self._diag_row("xunlei_rapid", "迅雷秒传链路", True, "迅雷秒传已关闭，跳过预检", skipped=True))

        hard = [row for row in checks if not row.get("skipped")]
        success = all(bool(row.get("ok")) for row in hard) if hard else True
        result = {
            "success": success,
            "message": "健康诊断通过" if success else "健康诊断发现问题，请按 checks / issues 排查",
            "checks": checks,
            "issues": issues[:12],
            "updated_at": self._now_text(),
        }
        self.save_data("full_diagnostics_last", result)
        return result

    def get_api(self):
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        if "/diagnostics/full" not in paths:
            apis.append({
                "path": "/diagnostics/full",
                "endpoint": self.api_full_diagnostics,
                "methods": ["POST"],
                "summary": "非破坏性检查来源健康、固定订阅搜索前置条件和迅雷秒传链路",
            })
        return apis


__all__ = ["GuangYaDiagnosticsV1100Mixin"]
