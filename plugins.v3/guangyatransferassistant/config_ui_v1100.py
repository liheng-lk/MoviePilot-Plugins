"""v1.10.0 配置页视觉与信息架构收口。

继续使用 MoviePilot 官方 Vuetify JSON 渲染协议，以生产级前端标准重排：主任务优先、协议细节折叠、
响应式栅格、统一圆角/间距/层级和清晰的帮助文本。配置键保持不变，升级不会丢配置。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


class GuangYaConfigUiV1100Mixin:
    """v1.10.0 高密度但不拥挤的配置工作台。"""

    build_id = "20260901-r11"
    _CARD_STYLE = "border:1px solid rgba(var(--v-border-color),.10);border-radius:18px;box-shadow:0 8px 26px rgba(15,23,42,.05);"

    @staticmethod
    def _field(model: str, label: str, *, md: int = 4, cols: int = 12, component: str = "VTextField", **props: Any) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": cols, "md": md},
            "content": [{
                "component": component,
                "props": {
                    "model": model,
                    "label": label,
                    "variant": "outlined",
                    "density": "comfortable",
                    "hide-details": False,
                    **props,
                },
            }],
        }

    @staticmethod
    def _switch(model: str, label: str, *, md: int = 3, hint: str = "") -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "model": model,
            "label": label,
            "density": "compact",
            "color": "primary",
            "inset": True,
        }
        if hint:
            props.update({"hint": hint, "persistent-hint": True})
        return {"component": "VCol", "props": {"cols": 12, "sm": 6, "md": md}, "content": [{"component": "VSwitch", "props": props}]}

    @staticmethod
    def _textarea(model: str, label: str, *, md: int = 6, rows: int = 3, hint: str = "") -> Dict[str, Any]:
        props: Dict[str, Any] = {
            "model": model,
            "label": label,
            "rows": rows,
            "auto-grow": True,
            "variant": "outlined",
            "density": "comfortable",
        }
        if hint:
            props.update({"hint": hint, "persistent-hint": True})
        return {"component": "VCol", "props": {"cols": 12, "md": md}, "content": [{"component": "VTextarea", "props": props}]}

    @classmethod
    def _section(cls, title: str, subtitle: str, icon: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4", "style": cls._CARD_STYLE},
            "content": [{
                "component": "VCardText",
                "props": {"class": "pa-4 pa-md-5"},
                "content": [
                    {"component": "div", "props": {"class": "d-flex align-center mb-4"}, "content": [
                        {"component": "VAvatar", "props": {"size": 38, "color": "primary", "variant": "tonal", "style": "border-radius:12px;"}, "content": [
                            {"component": "VIcon", "props": {"icon": icon, "size": 21}}
                        ]},
                        {"component": "div", "props": {"class": "ml-3"}, "content": [
                            {"component": "div", "props": {"style": "font-size:17px;font-weight:750;line-height:1.3;"}, "text": title},
                            {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;line-height:1.55;opacity:.62;"}, "text": subtitle},
                        ]},
                    ]},
                    *rows,
                ],
            }],
        }

    @classmethod
    def _advanced_panel(cls, title: str, icon: str, content: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "component": "VExpansionPanel",
            "props": {"style": "border-radius:14px;overflow:hidden;"},
            "content": [
                {"component": "VExpansionPanelTitle", "content": [
                    {"component": "VIcon", "props": {"icon": icon, "size": 19, "class": "mr-3", "color": "primary"}},
                    {"component": "span", "props": {"style": "font-weight:700;"}, "text": title},
                ]},
                {"component": "VExpansionPanelText", "content": content},
            ],
        }

    def get_form(self):
        old_form, defaults = super().get_form()
        defaults = dict(defaults or {})

        selected = deepcopy(self._find_model_props(old_form, "selected_subscriptions") or {
            "model": "selected_subscriptions", "items": [], "multiple": True, "chips": True,
        })
        selected.update({
            "model": "selected_subscriptions",
            "label": "由光鸭固定接管的订阅",
            "multiple": True,
            "chips": True,
            "closable-chips": True,
            "clearable": True,
            "variant": "outlined",
            "density": "comfortable",
            "prepend-inner-icon": "mdi-magnify",
            "hint": "可按剧名、年份、季、类型或订阅 ID 搜索；未勾选订阅继续走 MoviePilot 原生下载。",
            "persistent-hint": True,
        })
        save_path = deepcopy(self._find_model_props(old_form, "save_path") or {"model": "save_path"})
        save_path.update({
            "model": "save_path",
            "label": "光鸭目标文件夹",
            "variant": "outlined",
            "density": "comfortable",
            "hint": "可从已有目录选择，也可直接输入完整路径。",
            "persistent-hint": True,
        })

        hero = {
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "class": "mb-4",
                "style": "border-radius:18px;border:1px solid rgba(var(--v-theme-primary),.14);",
                "title": "统一资源决策",
                "text": "固定优先级：① 观影迅雷秒传 → ② 光鸭直接转存 → ③ Magnet → ④ ED2K。电视剧只处理 MoviePilot 真实缺集；低置信集号不会整包误存。",
            },
        }

        basic = self._section(
            "接管与保存",
            "只配置最常用的开关、订阅和目标目录；其它协议项不会干扰日常使用。",
            "mdi-tune-variant",
            [
                {"component": "VRow", "content": [
                    self._switch("enabled", "启用插件", md=3),
                    self._switch("notify", "任务通知", md=3),
                    self._switch("sync_subscription_progress", "同步追剧进度", md=3),
                    self._switch("protect_ongoing", "连载保护", md=3),
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VAutocomplete", "props": selected}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VCombobox", "props": save_path}]},
                    self._switch("create_media_folder", "媒体名子文件夹", md=2),
                    self._switch("media_only", "仅媒体 / 字幕", md=3),
                ]},
                {"component": "VRow", "content": [
                    self._switch("strict_subscription_rules", "遵循订阅质量规则", md=4),
                    self._switch("auto_transfer_on_refresh", "刷新后自动处理", md=4),
                    self._switch("daily_summary", "每日摘要", md=4),
                ]},
            ],
        )

        providers = self._section(
            "资源来源",
            "频道负责光鸭分享；观影同时提供迅雷 / Magnet / ED2K；外部接口用于补齐 Magnet / ED2K。",
            "mdi-database-search-outline",
            [
                {"component": "VRow", "content": [
                    self._textarea("channel_urls", "Telegram / 频道源", md=6, rows=3, hint="每行一个频道地址。"),
                    self._textarea(
                        "magnet_api_sources",
                        "Magnet / ED2K 搜索接口",
                        md=6,
                        rows=3,
                        hint="每行：名称|类型|地址|密钥。支持 tgsearch、limitless、json、torznab；v1.10 会自动兼容 q / kw / keyword / search 查询参数。",
                    ),
                ]},
                {"component": "VRow", "content": [
                    self._switch("provider_auto_search", "缺资源自动搜索", md=4),
                    self._switch("external_auto_dispatch", "新增来源自动处理", md=4),
                    self._switch("channel_external_auto_dispatch", "频道 Magnet / ED2K", md=4),
                ]},
            ],
        )

        viewing = self._section(
            "观影与迅雷秒传",
            "观影节点完成登录/搜索/downurl；发现迅雷分享后先做光鸭 userres 秒传，未命中才继续后续来源。",
            "mdi-flash-outline",
            [
                {"component": "VRow", "content": [
                    self._switch("viewing_enabled", "启用观影", md=3),
                    self._switch("viewing_auto_switch", "节点自动切换", md=3),
                    self._switch("viewing_auto_challenge", "自动计算验证", md=3),
                    self._switch("xunlei_flash_enabled", "迅雷秒传优先", md=3),
                ]},
                {"component": "VRow", "content": [
                    self._field(
                        "viewing_base_url",
                        "首选观影节点（可留空）",
                        md=12,
                        placeholder="https://www.星际穿越.com",
                        hint="留空时从发布页、缓存和备用节点自动选择；中文域名与 punycode 会归一为同一节点。",
                        **{"persistent-hint": True},
                    ),
                ]},
                {"component": "VRow", "content": [
                    self._field("viewing_username", "观影用户名 / 邮箱", md=6, autocomplete="username"),
                    self._field("viewing_password", "观影密码", md=6, type="password", autocomplete="current-password"),
                ]},
                {"component": "VRow", "content": [
                    self._textarea(
                        "viewing_cookie",
                        "观影 Cookie（可选）",
                        md=12,
                        rows=2,
                        hint="仅用于复用浏览器登录；只绑定首选节点，自动切换时不会跨域发送，也不会在状态 API 回显。",
                    ),
                ]},
            ],
        )

        advanced = {
            "component": "VCard",
            "props": {"variant": "flat", "class": "mb-4", "style": self._CARD_STYLE},
            "content": [{"component": "VCardText", "props": {"class": "pa-4 pa-md-5"}, "content": [
                {"component": "div", "props": {"class": "d-flex align-center mb-4"}, "content": [
                    {"component": "VAvatar", "props": {"size": 38, "color": "secondary", "variant": "tonal", "style": "border-radius:12px;"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-cog-outline", "size": 21}}]},
                    {"component": "div", "props": {"class": "ml-3"}, "content": [
                        {"component": "div", "props": {"style": "font-size:17px;font-weight:750;"}, "text": "高级设置"},
                        {"component": "div", "props": {"class": "mt-1", "style": "font-size:12px;opacity:.62;"}, "text": "默认无需展开；节点发现、代理、迅雷身份与重试参数集中在这里。"},
                    ]},
                ]},
                {"component": "VExpansionPanels", "props": {"variant": "accordion", "multiple": True, "style": "border-radius:14px;"}, "content": [
                    self._advanced_panel("节点发现与网络", "mdi-server-network", [
                        {"component": "VRow", "content": [
                            self._switch("provider_proxy", "观影 / 外部 API 使用代理", md=4),
                            self._switch("proxy", "频道使用代理", md=4),
                            self._field("viewing_node_cache_minutes", "节点缓存(分钟)", md=4, type="number", min="10", max="1440"),
                        ]},
                        {"component": "VRow", "content": [
                            self._textarea("viewing_registry_urls", "观影地址发布页", md=6, rows=2, hint="默认 gying.page / gying.si。"),
                            self._textarea("viewing_node_urls", "手动备用观影节点", md=6, rows=2, hint="每行一个；支持中文域名与 punycode。"),
                        ]},
                    ]),
                    self._advanced_panel("迅雷身份与秒传边界", "mdi-shield-key-outline", [
                        {"component": "VRow", "content": [
                            self._field("xunlei_client_id", "迅雷 Client ID", md=4),
                            self._field("xunlei_flash_max_files", "单分享文件上限", md=4, type="number", min="1", max="500"),
                            self._field("provider_timeout", "外部请求超时(秒)", md=4, type="number"),
                        ]},
                        {"component": "VRow", "content": [
                            self._field("xunlei_device_id", "迅雷 Device ID（通常自动生成）", md=6, placeholder="手工 captcha_token 时填写其对应 device_id"),
                            self._field("xunlei_captcha_token", "迅雷 captcha_token（通常自动获取）", md=6, type="password", autocomplete="off"),
                        ]},
                        {"component": "VRow", "content": [
                            self._textarea("xunlei_captcha_init_json", "迅雷 captcha/init 请求体（可选兜底）", md=12, rows=2, hint="自动初始化失败时才需要粘贴；不会在公开 API 回显。"),
                        ]},
                        {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "style": "border-radius:12px;", "text": "CID 只读取 3×20KiB Range 样本；服务器忽略中段/尾段 Range 时直接放弃 CID，不会下载整部文件。"}},
                    ]),
                    self._advanced_panel("任务与重试", "mdi-timer-refresh-outline", [
                        {"component": "VRow", "content": [
                            self._field("provider_result_limit", "外部候选上限", md=3, type="number"),
                            self._field("episode_auto_confidence", "拆包置信度", md=3, type="number", step="0.01", min="0.80", max="1.00"),
                            self._field("offline_poll_minutes", "云任务轮询(分钟)", md=3, type="number"),
                            self._field("offline_retry_minutes", "云任务重试(分钟)", md=3, type="number"),
                        ]},
                        {"component": "VRow", "content": [
                            self._field("offline_max_attempts", "最大云任务重试", md=3, type="number"),
                            self._field("history_pages", "每频道历史页数", md=3, type="number"),
                            self._field("max_files_per_run", "单次最多文件", md=3, type="number"),
                            self._field("retry_minutes", "转存失败重试(分钟)", md=3, type="number"),
                        ]},
                        {"component": "VRow", "content": [
                            self._field("refresh_minutes", "频道刷新(分钟)", md=3, type="number"),
                            self._field("max_share_files", "单分享扫描上限", md=3, type="number"),
                            self._field("ongoing_guard_days", "连载等待(天)", md=3, type="number"),
                            self._field("summary_cron", "每日摘要 Cron", md=3),
                        ]},
                        {"component": "VRow", "content": [self._switch("clear_inventory", "保存时清空去重记录（一次性）", md=12, hint="仅故障恢复时使用；保存后会自动关闭。")]} ,
                    ]),
                ]},
            ]}],
        }

        return [{"component": "VForm", "content": [hero, basic, providers, viewing, advanced]}], defaults


__all__ = ["GuangYaConfigUiV1100Mixin"]
