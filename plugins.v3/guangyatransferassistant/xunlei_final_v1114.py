"""v1.10.14 迅雷最终请求合同。

在 governance/runtime_fix 之上只收口两件与真实迅雷 Web 行为直接相关的事情：
- 用户提供真实 captcha_token + Device ID 时，匿名分享请求不额外强塞浏览器 profile 的
  x-client-version；保留真实 client/device/captcha 三元组，行为与用户验证可用的脚本一致；
- captcha 熔断打开后，本批其余迅雷候选在进入分享 API 前直接跳过，不再产生 20 条本地
  “验证码无效”异常，更不会继续访问 api-pan.xunlei.com。Magnet/ED2K 匹配不受影响。
"""

from __future__ import annotations

from typing import Any, Dict

from .governance_v1114 import GuangYaGovernanceV1114Mixin


class GuangYaXunleiFinalV1114Mixin(GuangYaGovernanceV1114Mixin):
    """最终迅雷设备/captcha 批处理边界。"""

    build_id = "20260902-r25"

    def _xunlei_headers(self, action: str, *, refresh: bool = False) -> Dict[str, str]:
        headers = dict(super()._xunlei_headers(action, refresh=refresh) or {})
        configured_token = str(getattr(self, "_xunlei_captcha_token", "") or "").strip()
        configured_device = str(getattr(self, "_xunlei_device_id", "") or "").strip()
        actual_token = str(headers.get("x-captcha-token") or "").strip()
        # 用户脚本验证可工作的匿名分享请求只要求真实 client/device/captcha；
        # 当正在使用用户提供的真实 pair 时，不覆盖它所来自页面的 client-version 语义。
        if configured_token and configured_device and actual_token == configured_token:
            headers.pop("x-client-version", None)
            headers.pop("X-Client-Version", None)
        return headers

    def _provider_candidate_matches(self, subscribe: Any, candidate: Dict[str, Any]) -> bool:
        # 只在迅雷候选批处理中生效；退出迅雷批次后 Magnet/ED2K 继续使用正常匹配链。
        if (
            bool(getattr(self, "_xunlei_batch_active_v1114", False))
            and bool(getattr(self, "_xunlei_captcha_circuit_open_v1113", False))
        ):
            return False
        return bool(super()._provider_candidate_matches(subscribe, candidate))

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        self._xunlei_batch_active_v1114 = True
        try:
            result = dict(super()._dispatch_xunlei_flash(subscribe) or {})
        finally:
            self._xunlei_batch_active_v1114 = False
        if result.get("captcha_circuit_open"):
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【迅雷秒传】captcha 熔断已生效，本批剩余迅雷候选已直接跳过；立即回退下一来源",
            )
        return result


__all__ = ["GuangYaXunleiFinalV1114Mixin"]
