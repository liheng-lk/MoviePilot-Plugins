"""v1.10.9 观影登录面板文案适配。

v1.10.9 默认自动登录，人工汉字验证码只在站点明确要求时出现；因此旧版
“人工认证/开始人工认证”文案会造成误导。本层只改展示文字，不改变 API 或会话协议。

v1.10.10 继承 PanSou challenge 层；v1.10.11 修正远程 PoW 计时与验真；
v1.10.12 再由 ``GuangYaGyingBrowserProfileV1112Mixin`` 把 challenge、PoW、登录、
搜索和 downurl 收口到同一个 MoviePilot CloakBrowser 上下文；同时继承
``browser_verified`` 竞态保护，并对齐 MoviePilot 宿主的 viewport/humanize 配置。
v1.10.13 在宿主 CloakBrowser 确认不可用、稳定回退 PanSou requests 后，保留当前
节点自己的验证 Cookie，避免每次订阅搜索都重复执行远程 PoW；并接入迅雷 captcha
设备合同、自愈熔断与迅雷秒传/Magnet/ED2K 云添加成功通知层。
v1.10.14 增加迅雷最终真实设备合同、自动检索冷却/去自激、云添加完成闭环和外部资源质量/字幕门禁。
v1.10.15 把频道改为真正的增量事件驱动：频道资源保留 7 天缓存，仅新增资源命中订阅时执行；观影与通用 Provider 改为独立冷却轮询。
"""

from __future__ import annotations

from typing import Any

from .channel_event_guard_v1115 import GuangYaChannelEventGuardV1115Mixin


_REPLACEMENTS_V1109 = {
    "观影人工认证": "观影登录",
    "开始人工认证": "建立观影会话",
    "当前观影站点登录会触发汉字点击验证码。插件不会自动识别验证码；点击“开始人工认证”后，在这里按提示亲自点击即可。": (
        "插件会优先自动完成浏览器计算验证和账号密码登录；只有站点明确要求点击验证时，"
        "这里才会显示汉字验证码，由你本人完成。"
    ),
    "PoW 自动恢复；汉字点击由你本人完成；成功后复用同一 Session 并持久化登录态。": (
        "PoW 自动恢复；账号密码自动登录；仅在站点明确要求时由你本人完成汉字点击验证码。"
    ),
}


def _rewrite_text_v1109(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_text_v1109(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_rewrite_text_v1109(child) for child in value]
    if isinstance(value, tuple):
        return tuple(_rewrite_text_v1109(child) for child in value)
    if isinstance(value, str):
        output = value
        for old, new in _REPLACEMENTS_V1109.items():
            output = output.replace(old, new)
        return output
    return value


class GuangYaGyingUiV1109Mixin(GuangYaChannelEventGuardV1115Mixin):
    """自动登录优先 UI，并启用最终迅雷/检索/质量/频道事件/完成治理链。"""

    build_id = "20260902-r26"

    def _gying_auth_panel(self):
        return _rewrite_text_v1109(super()._gying_auth_panel())


__all__ = ["GuangYaGyingUiV1109Mixin"]
