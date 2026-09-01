"""v1.10.0 光鸭转存助手控制台。

MoviePilot 插件页由宿主 Vuetify JSON 渲染，不直接加载 React/Tailwind。这里按同等设计标准
重构：统一 18px 圆角、轻边框/阴影、响应式 12/6/3 栅格、明确层级、状态色、焦点可读的
按钮与紧凑数据表，并把“搜索缺失资源 / 秒传预检”变成首页一等操作。
"""

from __future__ import annotations

from typing import Any, Dict, List


class GuangYaConsoleUiV1100Mixin:
    """生产化、响应式单屏控制台。"""

    build_id = "20260901-r11"

    _CARD_STYLE = (
        "border:1px solid rgba(var(--v-border-color),.10);"
        "border-radius:18px;"
        "box-shadow:0 10px 30px rgba(15,23,42,.06);"
        "overflow:hidden;"
    )
    _HERO_STYLE = (
        "border:1px solid rgba(var(--v-theme-primary),.16);"
        "border-radius:22px;"
        "background:linear-gradient(135deg,rgba(var(--v-theme-primary),.16) 0%,"
        "rgba(var(--v-theme-secondary),.08) 52%,rgba(var(--v-theme-surface),1) 100%);"
        "box-shadow:0 16px 40px rgba(15,23,42,.08);overflow:hidden;"
    )

    @staticmethod
    def _action(text: str, icon: str, path: str, *, color: str = "primary", variant: str = "tonal") -> Dict[str, Any]:
        return {
            "component": "VBtn",
            "props": {
                "size": "small",
                "variant": variant,
                "color": color,
                "prepend-icon": icon,
                "class": "mr-2 mb-2",
                "style": "border-radius:12px;min-height:38px;font-weight:600;letter-spacing:.01em;",
                "aria-label": text,
            },
            "text": text,
            "events": {"click": {"api": f"plugin/GuangYaTransferAssistant{path}", "method": "post"}},
        }

    @staticmethod
    def _status_chip(label: str, ok: bool, *, pending: bool = False) -> Dict[str, Any]:
        color = "warning" if pending else ("success" if ok else "error")
        icon = "mdi-clock-outline" if pending else ("mdi-check-circle-outline" if ok else "mdi-alert-circle-outline")
        return {
            "component": "VChip",
            "props": {
                "size": "small",
                "variant": "tonal",
                "color": color,
                "prepend-icon": icon,
                "class": "mr-2 mb-2",
                "style": "border-radius:999px;font-weight:600;",
            },
            "text": label,
        }

    @classmethod
    def _metric(cls, title: str, value: str, subtitle: str, icon: str, color: str = "primary") -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": 6, "md": 3},
            "content": [{
                "component": "VCard",
                "props": {"variant": "flat", "style": cls._CARD_STYLE, "class": "h-100"},
                "content": [{
                    "component": "VCardText",
                    "content": [
                        {"component": "div", "props": {"class": "d-flex align-center justify-space-between mb-3"}, "content": [
                            {"component": "div", "props": {"style": "font-size:13px;font-weight:600;opacity:.68;"}, "text": title},
                            {"component": "VAvatar", "props": {"size": 34, "color": color, "variant": "tonal", "style": "border-radius:11px;"}, "content": [
                                {"component": "VIcon", "props": {"icon": icon, "size": 19}}
                            ]},
                        ]},
                        {"component": "div", "props": {"style": "font-size:28px;line-height:1.15;font-weight:750;letter-spacing:-.02em;"}, "text": value},
                        {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.5;opacity:.62;"}, "text": subtitle},
                    ],
                }],
            }],
        }

    @classmethod
    def _surface(cls, title: str, subtitle: str, content: List[Dict[str, Any]], *, icon: str = "") -> Dict[str, Any]:
        header: List[Dict[str, Any]] = []
        if icon:
            header.append({"component": "VAvatar", "props": {"size": 36, "color": "primary", "variant": "tonal", "style": "border-radius:12px;"}, "content": [
                {"component": "VIcon", "props": {"icon": icon, "size": 20}}
            ]})
        header.append({"component": "div", "props": {"class": "ml-3" if icon else ""}, "content": [
            {"component": "div", "props": {"style": "font-size:17px;font-weight:700;line-height:1.3;"}, "text": title},
            {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.5;opacity:.62;"}, "text": subtitle},
        ]})
        return {
            "component": "VCard",
            "props": {"variant": "flat", "style": cls._CARD_STYLE, "class": "mb-4"},
            "content": [
                {"component": "VCardText", "content": [
                    {"component": "div", "props": {"class": "d-flex align-center mb-4"}, "content": header},
                    *content,
                ]},
            ],
        }

    def _runtime_health_rows(self, overview: Dict[str, Any]) -> List[Dict[str, Any]]:
        viewing = dict(overview.get("viewing") or {})
        viewing_enabled = bool(viewing.get("enabled"))
        viewing_ok = viewing_enabled and str(viewing.get("status") or "") == "ok"
        viewing_node = str(viewing.get("active_node") or "未选择")

        xunlei_status = {}
        try:
            xunlei_status = dict((self.api_xunlei_runtime_status() or {}).get("data") or {})
        except Exception:
            pass
        xunlei_enabled = bool(getattr(self, "_xunlei_flash_enabled", True))
        xunlei_ready = bool(xunlei_status.get("captcha_ready") and xunlei_status.get("device_ready"))

        provider_defs = list(self._parse_provider_defs())
        provider_last = self.get_data("provider_test_last") or {}
        provider_states = list(provider_last.get("providers") or []) if isinstance(provider_last, dict) else []
        configured_api_states = [row for row in provider_states if str(row.get("provider") or "") != "viewing"]
        if configured_api_states:
            api_ok = all(bool(row.get("success")) for row in configured_api_states)
        else:
            api_ok = bool(provider_defs)

        try:
            client, api = self._get_guangya_runtime()
            guangya_ok = bool(client and api)
        except Exception:
            guangya_ok = False

        rows = [
            ("观影 GYING", viewing_ok, "未启用" if not viewing_enabled else viewing_node, "mdi-movie-search-outline"),
            ("迅雷秒传", xunlei_ready and xunlei_enabled, "已关闭" if not xunlei_enabled else str(xunlei_status.get("message") or "等待预检"), "mdi-flash-outline"),
            ("Magnet / ED2K API", api_ok, f"已配置 {len(provider_defs)} 个接口" if provider_defs else "未配置外部 API", "mdi-magnet-on"),
            ("光鸭运行时", guangya_ok, "客户端与存储 API 已就绪" if guangya_ok else "未运行或未登录", "mdi-cloud-check-outline"),
        ]
        return [{
            "component": "VCol",
            "props": {"cols": 12, "sm": 6, "md": 3},
            "content": [{
                "component": "VSheet",
                "props": {
                    "class": "pa-3 h-100",
                    "style": "border:1px solid rgba(var(--v-border-color),.10);border-radius:14px;background:rgba(var(--v-theme-surface-variant),.20);",
                },
                "content": [
                    {"component": "div", "props": {"class": "d-flex align-center mb-2"}, "content": [
                        {"component": "VIcon", "props": {"icon": icon, "size": 19, "color": "success" if ok else "warning", "class": "mr-2"}},
                        {"component": "span", "props": {"style": "font-size:13px;font-weight:700;"}, "text": name},
                    ]},
                    {"component": "div", "props": {"style": "font-size:12px;line-height:1.55;opacity:.68;word-break:break-word;"}, "text": detail},
                ],
            }],
        } for name, ok, detail, icon in rows]

    def get_page(self):
        overview = self._status_overview_v191()
        sources = dict(overview.get("sources") or {})
        search_last = self.get_data("provider_search_last") or {}
        preflight_last = self.get_data("xunlei_preflight_last") or {}
        attention_cards = self._attention_cards(overview)
        active_cards = self._active_cards(overview)

        overall = str(overview.get("overall") or "warning")
        healthy = overall == "healthy"
        hero_status = "运行正常" if healthy else ("存在关键异常" if overall == "error" else "有待处理事项")
        hero_color = "success" if healthy else ("error" if overall == "error" else "warning")

        hero = {
            "component": "VCard",
            "props": {"variant": "flat", "style": self._HERO_STYLE, "class": "mb-4"},
            "content": [{
                "component": "VCardText",
                "props": {"class": "pa-5 pa-md-6"},
                "content": [
                    {"component": "VRow", "props": {"align": "center"}, "content": [
                        {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                            {"component": "div", "props": {"class": "d-flex align-center mb-3"}, "content": [
                                {"component": "VAvatar", "props": {"size": 46, "color": "primary", "variant": "tonal", "style": "border-radius:15px;"}, "content": [
                                    {"component": "VIcon", "props": {"icon": "mdi-cloud-sync-outline", "size": 25}}
                                ]},
                                {"component": "div", "props": {"class": "ml-3"}, "content": [
                                    {"component": "div", "props": {"style": "font-size:22px;line-height:1.25;font-weight:800;letter-spacing:-.02em;"}, "text": "光鸭转存助手"},
                                    {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;opacity:.62;"}, "text": f"v{overview.get('version')} · build {overview.get('build')} · 频道 {overview.get('channel_updated')}"},
                                ]},
                            ]},
                            {"component": "div", "props": {"style": "font-size:14px;line-height:1.7;max-width:760px;opacity:.78;"}, "text": "按 MoviePilot 实际缺失内容统一决策，先秒传、再直存、最后才进入光鸭原生 Magnet / ED2K 云添加。搜索和秒传诊断已放到首页，不再藏在 API。"},
                            {"component": "div", "props": {"class": "d-flex flex-wrap mt-4"}, "content": [
                                self._status_chip(hero_status, healthy, pending=not healthy and overall != "error"),
                                {"component": "VChip", "props": {"size": "small", "variant": "tonal", "color": hero_color, "class": "mr-2 mb-2", "style": "border-radius:999px;font-weight:600;"}, "text": f"需要处理 {int(overview.get('attention_count') or 0)}"},
                            ]},
                        ]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                            {"component": "VSheet", "props": {"class": "pa-4", "style": "border-radius:16px;background:rgba(var(--v-theme-surface),.72);backdrop-filter:blur(12px);"}, "content": [
                                {"component": "div", "props": {"style": "font-size:12px;font-weight:700;opacity:.60;"}, "text": "固定执行优先级"},
                                {"component": "div", "props": {"class": "d-flex flex-wrap mt-3"}, "content": [
                                    {"component": "VChip", "props": {"size": "small", "color": "primary", "variant": "flat", "class": "mr-2 mb-2"}, "text": "① 迅雷秒传"},
                                    {"component": "VChip", "props": {"size": "small", "color": "info", "variant": "tonal", "class": "mr-2 mb-2"}, "text": "② 光鸭直存"},
                                    {"component": "VChip", "props": {"size": "small", "color": "secondary", "variant": "tonal", "class": "mr-2 mb-2"}, "text": "③ Magnet"},
                                    {"component": "VChip", "props": {"size": "small", "variant": "outlined", "class": "mr-2 mb-2"}, "text": "④ ED2K"},
                                ]},
                            ]},
                        ]},
                    ]},
                ],
            }],
        }

        metrics = {"component": "VRow", "props": {"class": "mb-1"}, "content": [
            self._metric("固定转存", str(overview.get("selected") or 0), "由光鸭接管的 MoviePilot 订阅", "mdi-pin-outline"),
            self._metric("正在处理", str(len(overview.get("active_transfer_rows") or []) + len(overview.get("active_sources") or [])), "转存 + 原生云添加", "mdi-progress-clock", "info"),
            self._metric("需要处理", str(overview.get("attention_count") or 0), "失败或需要人工确认", "mdi-alert-outline", "warning"),
            self._metric("资源索引", str(overview.get("channel_count") or 0), f"Magnet {sources.get('magnet', 0)} · ED2K {sources.get('ed2k', 0)}", "mdi-database-search-outline", "secondary"),
        ]}

        actions = self._surface(
            "资源搜索与秒传",
            "先看运行时是否就绪，再对已选择订阅统一搜索观影迅雷、Magnet 与 ED2K；所有动作都使用同一套后端决策逻辑。",
            [
                {"component": "VRow", "content": self._runtime_health_rows(overview)},
                {"component": "VDivider", "props": {"class": "my-4"}},
                {"component": "div", "props": {"class": "d-flex flex-wrap"}, "content": [
                    self._action("搜索缺失资源", "mdi-database-search-outline", "/providers/search/selected", color="primary", variant="flat"),
                    self._action("检测资源来源", "mdi-access-point-check", "/providers/test", color="secondary"),
                    self._action("秒传预检", "mdi-flash-check-outline", "/xunlei/flash/preflight", color="warning"),
                    self._action("刷新观影节点", "mdi-server-network", "/viewing/nodes/refresh", color="info"),
                    self._action("刷新频道", "mdi-refresh", "/refresh", color="primary", variant="outlined"),
                    self._action("运行自检", "mdi-stethoscope", "/selfcheck", color="secondary", variant="text"),
                ]},
            ],
            icon="mdi-radar",
        )

        search_rows = []
        if isinstance(search_last, dict):
            for item in list(search_last.get("items") or [])[:12]:
                counts = dict(item.get("counts") or {})
                search_rows.append({
                    "title": f"{item.get('name') or '-'} {item.get('year') or ''}".strip(),
                    "keyword": str(item.get("keyword") or ""),
                    "xunlei": int(counts.get("xunlei") or 0),
                    "magnet": int(counts.get("magnet") or 0),
                    "ed2k": int(counts.get("ed2k") or 0),
                    "state": "可用" if item.get("success") else "未命中/异常",
                })
        search_content: List[Dict[str, Any]] = []
        if search_rows:
            search_content.append({
                "component": "VDataTable",
                "props": {
                    "density": "compact",
                    "items-per-page": 12,
                    "headers": [
                        {"title": "订阅", "key": "title"},
                        {"title": "搜索词", "key": "keyword"},
                        {"title": "迅雷", "key": "xunlei", "align": "end"},
                        {"title": "Magnet", "key": "magnet", "align": "end"},
                        {"title": "ED2K", "key": "ed2k", "align": "end"},
                        {"title": "状态", "key": "state"},
                    ],
                    "items": search_rows,
                    "style": "border-radius:14px;overflow:hidden;",
                },
            })
        else:
            search_content.append({"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "style": "border-radius:14px;", "text": "还没有搜索记录。点击“搜索缺失资源”后，这里会按订阅展示迅雷 / Magnet / ED2K 命中数量。"}})

        if isinstance(preflight_last, dict) and preflight_last.get("updated_at"):
            search_content.append({"component": "VAlert", "props": {
                "type": "success" if preflight_last.get("rapid_ready") else "warning",
                "variant": "tonal",
                "density": "compact",
                "class": "mt-3",
                "style": "border-radius:14px;",
                "text": f"秒传预检：{preflight_last.get('message') or '-'} · {preflight_last.get('updated_at')}",
            }})
        search_report = self._surface(
            "最近搜索结果",
            str(search_last.get("message") or "仅展示最近一次手动搜索；自动订阅处理仍按后台优先级持续执行。") if isinstance(search_last, dict) else "暂无搜索记录",
            search_content,
            icon="mdi-text-box-search-outline",
        )

        attention = self._surface(
            "需要处理",
            "只显示真正需要人工干预的异常；正常等待新资源、自动重试和完成历史不会污染首页。",
            attention_cards if attention_cards else [{"component": "VAlert", "props": {"type": "success", "variant": "tonal", "density": "compact", "style": "border-radius:14px;", "text": "当前没有需要人工处理的事项。"}}],
            icon="mdi-shield-check-outline",
        )

        active = self._surface(
            "正在处理",
            "最多展示 6 条当前在途任务；完成后自动退出本区。",
            active_cards if active_cards else [{"component": "div", "props": {"style": "font-size:13px;opacity:.62;padding:4px 0;"}, "text": "当前没有正在处理的转存或云添加任务。"}],
            icon="mdi-progress-clock",
        )

        return [hero, metrics, actions, search_report, attention, active]


__all__ = ["GuangYaConsoleUiV1100Mixin"]
