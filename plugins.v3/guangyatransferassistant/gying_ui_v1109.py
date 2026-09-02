"""v1.10.9 观影登录面板文案适配。

v1.10.9 默认自动登录，人工汉字验证码只在站点明确要求时出现；因此旧版
“人工认证/开始人工认证”文案会造成误导。本层只改展示文字，不改变 API 或会话协议。
"""

from __future__ import annotations

from typing import Any


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


class GuangYaGyingUiV1109Mixin:
    """把旧人工认证面板改成自动登录优先的真实状态说明。"""

    build_id = "20260902-r20"

    def _gying_auth_panel(self):
        return _rewrite_text_v1109(super()._gying_auth_panel())


__all__ = ["GuangYaGyingUiV1109Mixin"]
