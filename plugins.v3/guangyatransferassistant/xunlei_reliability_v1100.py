"""v1.10.0 迅雷秒传运行可靠性层。

重点修复 Range 服务器忽略 Range 时 requests 先把整部大文件读进内存的风险：
所有 CID 样本均使用 stream=True，单段最多读取 20KiB；非零 Range 若返回 200 立即放弃，
绝不通过跳读整文件来计算 CID。另增加非破坏性的秒传预检 API，分别报告观影、迅雷身份和
光鸭运行时是否就绪。

v1.12.5 追加跨关键词重试边界：一次迅雷秒传调用内部即使会降级多个 GYING 关键词，
只要底层迅雷分享 API 已打开 captcha 熔断，就把该熔断视为整个召回轮次的终止事实，
不能因为下一档关键词重新进入 RuntimeFix 并重置 captcha circuit 后再次访问迅雷分享接口。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List

import requests

from .provider_sources_v192 import _proxy_dict


_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(?:\d+|\*)", re.I)


class GuangYaXunleiReliabilityV1100Mixin:
    """最终 CID 采样边界、秒传链路预检与跨关键词 captcha 熔断保持。"""

    build_id = "20260901-r11"
    _CID_SAMPLE_SIZE = 20 * 1024

    @staticmethod
    def _read_limited_stream(response: requests.Response, limit: int) -> bytes:
        """只消费 limit 字节，达到上限立即停止；调用方负责 close。"""
        limit = max(0, int(limit or 0))
        if limit <= 0:
            return b""
        data = bytearray()
        for chunk in response.iter_content(chunk_size=min(8192, limit)):
            if not chunk:
                continue
            remaining = limit - len(data)
            if remaining <= 0:
                break
            data.extend(chunk[:remaining])
            if len(data) >= limit:
                break
        return bytes(data)

    def _merge_xunlei_rounds_v1125(self, base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        """让一次秒传调用里的 captcha 熔断跨关键词保持，避免宽搜重新打迅雷分享 API。"""
        merged = dict(super()._merge_xunlei_rounds_v1125(base, extra) or {})
        captcha_open = bool((base or {}).get("captcha_circuit_open")) or bool(
            (extra or {}).get("captcha_circuit_open")
        )
        if not captcha_open:
            return merged

        merged["captcha_circuit_open"] = True
        # RecallGuard 的关键词循环在 merge 后会检查同一个 thread-local stop 标记。
        # 这里不伪造 handled=True：captcha 失败只终止迅雷继续扩大搜索，后续 Magnet/ED2K
        # 仍应按既有来源优先级继续执行。
        local_getter = getattr(self, "_recall_retry_local_v1125", None)
        if callable(local_getter):
            try:
                local_getter().stop_after_failure = True
            except Exception:
                pass
        return merged

    def _xunlei_compute_triple_cid(self, download_url: str, file_size: int) -> str:
        download_url = str(download_url or "").strip()
        try:
            file_size = int(file_size or 0)
        except (TypeError, ValueError):
            file_size = 0
        if not download_url or file_size <= 0:
            return ""

        sample_size = self._CID_SAMPLE_SIZE
        if file_size <= sample_size:
            ranges = [(0, file_size - 1)] * 3
        else:
            ranges = [
                (0, min(sample_size - 1, file_size - 1)),
                (file_size // 3, min(file_size // 3 + sample_size - 1, file_size - 1)),
                (max(0, file_size - sample_size), file_size - 1),
            ]

        session = requests.Session()
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        timeout = int(getattr(self, "_provider_timeout", 15) or 15)
        chunks: List[bytes] = []

        for start, end in ranges:
            expected = end - start + 1
            response: requests.Response | None = None
            try:
                response = session.get(
                    download_url,
                    headers={
                        "Range": f"bytes={start}-{end}",
                        "Referer": "https://pan.xunlei.com/",
                        "Origin": "https://pan.xunlei.com",
                        "Accept-Encoding": "identity",
                    },
                    timeout=timeout,
                    stream=True,
                    allow_redirects=True,
                )
                if response.status_code == 206:
                    content_range = str(response.headers.get("Content-Range") or "")
                    matched = _CONTENT_RANGE_RE.search(content_range)
                    if matched and (int(matched.group(1)) != start or int(matched.group(2)) != end):
                        return ""
                    content = self._read_limited_stream(response, expected)
                    if len(content) != expected:
                        return ""
                    chunks.append(content)
                    continue

                if response.status_code == 200:
                    # Range 被忽略时只能安全取得文件开头；中段/尾段若继续读取就会为了
                    # 20KiB 样本跳过数 GB 数据，违反秒传“绝不整文件中转”的边界。
                    if start != 0:
                        return ""
                    content = self._read_limited_stream(response, expected)
                    if len(content) != expected:
                        return ""
                    chunks.append(content)
                    continue
                return ""
            except Exception:
                return ""
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
        return hashlib.sha1(b"".join(chunks)).hexdigest()

    def _xunlei_rapid_readiness(self) -> Dict[str, Any]:
        stages: List[Dict[str, Any]] = []

        try:
            client, api = self._get_guangya_runtime()
            request = getattr(client, "_request", None) if client else None
            guangya_ok = bool(client and api and callable(request))
            stages.append({
                "key": "guangya",
                "name": "光鸭运行时",
                "ok": guangya_ok,
                "message": "已取得登录客户端与存储 API" if guangya_ok else "光鸭云盘助手未运行、未登录或缺少 userres 请求能力",
            })
        except Exception as err:
            guangya_ok = False
            stages.append({"key": "guangya", "name": "光鸭运行时", "ok": False, "message": str(err)[:240]})

        try:
            headers = self._xunlei_headers("get:/drive/v1/share")
            captcha_ok = bool(headers.get("x-captcha-token"))
            device_ok = bool(headers.get("x-device-id"))
            client_ok = bool(headers.get("x-client-id"))
            xunlei_ok = captcha_ok and device_ok and client_ok
            stages.append({
                "key": "xunlei_identity",
                "name": "迅雷匿名分享身份",
                "ok": xunlei_ok,
                "message": (
                    "captcha / device / client 已就绪"
                    if xunlei_ok
                    else "迅雷 captcha、device 或 client 尚未就绪"
                ),
                "captcha_ready": captcha_ok,
                "device_ready": device_ok,
                "client_ready": client_ok,
            })
        except Exception as err:
            xunlei_ok = False
            stages.append({"key": "xunlei_identity", "name": "迅雷匿名分享身份", "ok": False, "message": str(err)[:240]})

        if bool(getattr(self, "_viewing_enabled", False)):
            try:
                _, login = self._viewing_session()
                viewing_ok = bool(login.get("success"))
                stages.append({
                    "key": "viewing",
                    "name": "观影会话",
                    "ok": viewing_ok,
                    "message": str(login.get("message") or ("已就绪" if viewing_ok else "不可用"))[:240],
                    "node": str(login.get("node") or ""),
                    "login_mode": str(login.get("mode") or ""),
                })
            except Exception as err:
                viewing_ok = False
                stages.append({"key": "viewing", "name": "观影会话", "ok": False, "message": str(err)[:240]})
        else:
            viewing_ok = False
            stages.append({"key": "viewing", "name": "观影会话", "ok": False, "message": "观影未启用"})

        ready = bool(guangya_ok and xunlei_ok and viewing_ok and getattr(self, "_xunlei_flash_enabled", True))
        return {
            "success": ready,
            "rapid_ready": ready,
            "flash_enabled": bool(getattr(self, "_xunlei_flash_enabled", True)),
            "stages": stages,
            "message": "迅雷秒传链路预检通过" if ready else "迅雷秒传链路尚未完全就绪，请查看 stages",
            "updated_at": self._now_text(),
        }

    def api_xunlei_preflight(self) -> Dict[str, Any]:
        result = self._xunlei_rapid_readiness()
        self.save_data("xunlei_preflight_last", result)
        return result

    def api_xunlei_flash_test(self, share_url: str = "", passcode: str = "") -> Dict[str, Any]:
        """分享读取测试 + 秒传运行时就绪度；不创建光鸭文件/上传任务。"""
        share_result = dict(super().api_xunlei_flash_test(share_url=share_url, passcode=passcode) or {})
        readiness = self._xunlei_rapid_readiness()
        share_ok = bool(share_result.get("success"))
        combined = {
            **share_result,
            "success": bool(share_ok and readiness.get("rapid_ready")),
            "share_read_success": share_ok,
            "rapid_ready": bool(readiness.get("rapid_ready")),
            "preflight": readiness,
        }
        if share_ok and not readiness.get("rapid_ready"):
            combined["message"] = f"迅雷分享可读，但秒传运行时未就绪：{readiness.get('message')}"
        self.save_data("xunlei_flash_test_last", {
            "success": combined.get("success"),
            "share_read_success": combined.get("share_read_success"),
            "rapid_ready": combined.get("rapid_ready"),
            "message": str(combined.get("message") or "")[:300],
            "updated_at": self._now_text(),
        })
        return combined

    def get_api(self):
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        if "/xunlei/flash/preflight" not in paths:
            apis.append({
                "path": "/xunlei/flash/preflight",
                "endpoint": self.api_xunlei_preflight,
                "methods": ["POST"],
                "summary": "非破坏性检测观影/迅雷/光鸭秒传链路",
            })
        return apis


__all__ = ["GuangYaXunleiReliabilityV1100Mixin"]
