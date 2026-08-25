"""v3.4.7：光鸭上游 DNS/连接异常的降噪、退避与自动整理保护。

目标：
1. DNS/连接瞬断不再由 legacy 客户端每次都打 ERROR；统一在兼容层重试并节流告警。
2. 同一主机连续失败后进入短暂熔断，避免目录扫描、账号页刷新和整理链一起放大故障。
3. 用户信息/空间信息短缓存，网络抖动时复用最近成功值，不清空登录态。
4. 自动整理在文件 API 熔断期间安全延后；扫描中途断网时标记 truncated，禁止用不完整
   inventory 清理已有状态。

不改变光鸭 API 业务语义，也不绕过 MoviePilot 的识别、分类、整理规则。
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import requests

from app.log import logger

from .guangya_client import GuangYaClient
from .organizer_folder_stream import GuangYaFolderStreamMixin


_TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
_RETRY_DELAYS = (1.0, 2.0)
_CONTROL_CACHE_TTL = 60.0
_MAX_CIRCUIT_SECONDS = 30.0
_WARN_INTERVAL = 30.0


def _host(url: str) -> str:
    return str(urlparse(str(url or "")).hostname or url or "unknown")


def _ensure_runtime(client: GuangYaClient) -> None:
    if getattr(client, "_guangya_network_v347_ready", False):
        return
    client._guangya_network_v347_ready = True
    client._guangya_network_lock = threading.RLock()
    client._guangya_network_hosts = {}
    client._guangya_control_cache = {}


def _state_for(client: GuangYaClient, host: str) -> Dict[str, Any]:
    _ensure_runtime(client)
    with client._guangya_network_lock:
        state = client._guangya_network_hosts.get(host)
        if state is None:
            state = {
                "failures": 0,
                "circuit_until": 0.0,
                "last_warn_at": 0.0,
                "last_error": "",
                "outage": False,
                "last_success_at": 0.0,
            }
            client._guangya_network_hosts[host] = state
        return state


def _transient_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("transient_network"):
        return True
    text = str(result.get("error") or result.get("msg") or "")
    markers = (
        "NameResolutionError",
        "Temporary failure in name resolution",
        "Failed to resolve",
        "ConnectionError",
        "Connection aborted",
        "Connection reset",
        "Read timed out",
        "ConnectTimeout",
        "ReadTimeout",
        "Max retries exceeded",
        "network_circuit_open",
    )
    return any(marker.casefold() in text.casefold() for marker in markers)


def _mark_success(client: GuangYaClient, host: str) -> None:
    state = _state_for(client, host)
    recovered = False
    with client._guangya_network_lock:
        recovered = bool(state.get("outage"))
        state["failures"] = 0
        state["circuit_until"] = 0.0
        state["last_error"] = ""
        state["outage"] = False
        state["last_success_at"] = time.time()
    if recovered:
        logger.info("【光鸭云盘助手】【网络】%s 已恢复，继续处理挂起任务", host)


def _mark_failure(client: GuangYaClient, host: str, error: str) -> float:
    state = _state_for(client, host)
    now_mono = time.monotonic()
    should_warn = False
    with client._guangya_network_lock:
        state["failures"] = int(state.get("failures") or 0) + 1
        failures = int(state["failures"])
        cooldown = min(5.0 * (2 ** max(failures - 1, 0)), _MAX_CIRCUIT_SECONDS)
        state["circuit_until"] = now_mono + cooldown
        state["last_error"] = str(error or "")
        state["outage"] = True
        last_warn_at = float(state.get("last_warn_at") or 0.0)
        if not last_warn_at or now_mono - last_warn_at >= _WARN_INTERVAL:
            state["last_warn_at"] = now_mono
            should_warn = True
    if should_warn:
        logger.warning(
            "【光鸭云盘助手】【网络】%s DNS/连接暂不可用，已完成本轮重试；"
            "暂停该主机请求 %.0fs，期间保留登录态和自动整理状态",
            host,
            cooldown,
        )
    return cooldown


def _circuit_result(client: GuangYaClient, url: str) -> Optional[Dict[str, Any]]:
    host = _host(url)
    state = _state_for(client, host)
    now_mono = time.monotonic()
    with client._guangya_network_lock:
        until = float(state.get("circuit_until") or 0.0)
        if until <= now_mono:
            return None
        retry_after = max(until - now_mono, 0.0)
        return {
            "msg": "error",
            "code": -1,
            "error": "network_circuit_open",
            "transient_network": True,
            "network_host": host,
            "retry_after": retry_after,
            "detail": str(state.get("last_error") or ""),
        }


def _request_once(
    client: GuangYaClient,
    *,
    method: str,
    url: str,
    data: Optional[dict],
    headers: Optional[dict],
    need_auth: bool,
    retry_on_401: bool,
    treat_http_error_as_response: bool,
    timeout: int,
) -> Dict[str, Any]:
    req_headers = client._session.headers.copy()
    if headers:
        req_headers.update(headers)
    if need_auth and client._access_token:
        req_headers.update(client._get_auth_headers())

    if need_auth:
        logger.debug(
            "【光鸭云盘助手】发起请求: %s %s, device_id=%s, access_token=%s, refresh_token=%s",
            method.upper(),
            url,
            client._device_id,
            client._mask_token(client._access_token),
            client._mask_token(client._refresh_token),
        )

    try:
        method_upper = method.upper()
        if method_upper == "GET":
            response = client._session.get(url, headers=req_headers, params=data, timeout=timeout)
        elif method_upper == "PUT":
            response = client._session.put(url, headers=req_headers, data=data, timeout=timeout)
        else:
            response = client._session.post(url, headers=req_headers, json=data, timeout=timeout)

        response.raise_for_status()
        if not response.text:
            return {"msg": "success", "code": 0}
        return response.json()

    except requests.exceptions.HTTPError as err:
        status_code = err.response.status_code if err.response is not None else None

        if status_code in _TRANSIENT_HTTP_STATUS:
            detail = f"{status_code} {err.response.reason}" if err.response is not None else str(err)
            try:
                if err.response is not None and err.response.text:
                    detail = f"{detail} - {err.response.text[:500]}"
            except Exception:
                pass
            return {
                "msg": "error",
                "code": status_code or -1,
                "error": detail,
                "transient_network": True,
                "network_kind": "http",
            }

        if treat_http_error_as_response and err.response is not None:
            try:
                return err.response.json()
            except Exception:
                return {
                    "msg": "error",
                    "code": status_code or -1,
                    "error": err.response.text[:500] if err.response.text else str(err),
                }

        if status_code == 401 and retry_on_401 and need_auth:
            logger.info(
                "【光鸭云盘助手】Token 失效，尝试刷新: access_token=%s, refresh_token=%s, device_id=%s",
                client._mask_token(client._access_token),
                client._mask_token(client._refresh_token),
                client._device_id,
            )
            if client.refresh_access_token():
                return client._request(
                    method=method,
                    url=url,
                    data=data,
                    headers=headers,
                    need_auth=need_auth,
                    retry_on_401=False,
                    treat_http_error_as_response=treat_http_error_as_response,
                    timeout=timeout,
                )

        detail = f"{status_code} {err.response.reason}" if err.response is not None else str(err)
        try:
            if err.response is not None and err.response.text:
                detail = f"{detail} - {err.response.text[:500]}"
        except Exception:
            pass

        logger.error("【光鸭云盘助手】请求失败: %s - %s", url, detail)
        return {"msg": "error", "code": -1, "error": detail}

    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ProxyError,
    ) as err:
        # 由外层统一重试和节流告警，避免 legacy 每个请求都打一条 ERROR。
        return {
            "msg": "error",
            "code": -1,
            "error": str(err),
            "transient_network": True,
            "network_kind": type(err).__name__,
        }

    except requests.exceptions.RequestException as err:
        # 参数、证书等非典型请求错误不做熔断，保留 ERROR 便于诊断。
        logger.error("【光鸭云盘助手】请求失败: %s - %s", url, err)
        return {"msg": "error", "code": -1, "error": str(err)}


def _request(
    client: GuangYaClient,
    method: str,
    url: str,
    data: dict = None,
    headers: dict = None,
    need_auth: bool = True,
    retry_on_401: bool = True,
    treat_http_error_as_response: bool = False,
    timeout: int = 30,
) -> Dict[str, Any]:
    _ensure_runtime(client)

    if circuit := _circuit_result(client, url):
        return circuit

    host = _host(url)
    last_result: Dict[str, Any] = {}
    max_attempts = len(_RETRY_DELAYS) + 1

    for attempt in range(1, max_attempts + 1):
        last_result = _request_once(
            client,
            method=method,
            url=url,
            data=data,
            headers=headers,
            need_auth=need_auth,
            retry_on_401=retry_on_401,
            treat_http_error_as_response=treat_http_error_as_response,
            timeout=timeout,
        )
        if not _transient_result(last_result):
            _mark_success(client, host)
            return last_result

        if attempt < max_attempts:
            delay = _RETRY_DELAYS[attempt - 1]
            logger.debug(
                "【光鸭云盘助手】【网络】%s 第 %s/%s 次失败，%.0fs 后重试: %s",
                host,
                attempt,
                max_attempts,
                delay,
                last_result.get("error") or last_result.get("msg"),
            )
            time.sleep(delay)

    cooldown = _mark_failure(
        client,
        host,
        str(last_result.get("error") or last_result.get("msg") or last_result),
    )
    result = dict(last_result or {})
    result["transient_network"] = True
    result["network_host"] = host
    result["retry_after"] = cooldown
    return result


def _cache_success(result: Any) -> bool:
    if not isinstance(result, dict) or _transient_result(result):
        return False
    if result.get("error"):
        return False
    code = result.get("code")
    return code in (None, 0) or result.get("msg") == "success" or isinstance(result.get("data"), dict)


def _cached_control_call(
    client: GuangYaClient,
    key: str,
    call: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    _ensure_runtime(client)
    now = time.monotonic()

    with client._guangya_network_lock:
        cached = client._guangya_control_cache.get(key)
        if cached and now - float(cached.get("at") or 0.0) < _CONTROL_CACHE_TTL:
            return copy.deepcopy(cached["value"])

    result = call() or {}
    if _cache_success(result):
        with client._guangya_network_lock:
            client._guangya_control_cache[key] = {
                "at": time.monotonic(),
                "value": copy.deepcopy(result),
            }
        return result

    if _transient_result(result):
        with client._guangya_network_lock:
            cached = client._guangya_control_cache.get(key)
            if cached:
                stale = copy.deepcopy(cached["value"])
                stale["_guangya_stale_cache"] = True
                stale["_guangya_network_unavailable"] = True
                return stale

    return result


def _network_status(client: GuangYaClient, host: Optional[str] = None) -> Dict[str, Any]:
    _ensure_runtime(client)
    now_mono = time.monotonic()
    with client._guangya_network_lock:
        if host:
            states = {host: dict(client._guangya_network_hosts.get(host) or {})}
        else:
            states = {
                name: dict(value)
                for name, value in client._guangya_network_hosts.items()
            }

    hosts: Dict[str, Any] = {}
    available = True
    for name, state in states.items():
        until = float(state.get("circuit_until") or 0.0)
        retry_after = max(until - now_mono, 0.0)
        blocked = retry_after > 0
        if blocked:
            available = False
        hosts[name] = {
            "available": not blocked,
            "degraded": bool(state.get("outage")),
            "failures": int(state.get("failures") or 0),
            "retry_after": retry_after,
            "last_error": str(state.get("last_error") or ""),
            "last_success_at": float(state.get("last_success_at") or 0.0),
        }
    return {"available": available, "hosts": hosts}


def _api_network_status(plugin: Any) -> Dict[str, Any]:
    api = getattr(plugin, "_guangya_api", None)
    client = getattr(api, "client", None) or getattr(plugin, "_client", None)
    if not client:
        return {"available": True, "hosts": {}}
    getter = getattr(client, "get_network_status", None)
    if not callable(getter):
        return {"available": True, "hosts": {}}
    host = _host(getattr(client, "API_BASE_URL", "https://api.guangyapan.com"))
    try:
        return dict(getter(host) or {})
    except Exception:
        return {"available": True, "hosts": {}}


def _network_retry_after(status: Dict[str, Any]) -> float:
    values = [
        float(item.get("retry_after") or 0.0)
        for item in (status.get("hosts") or {}).values()
        if isinstance(item, dict)
    ]
    return max(values or [0.0])


def install_network_resilience_v347() -> None:
    if getattr(GuangYaClient, "_guangya_network_resilience_v347", False):
        return

    original_user_info = GuangYaClient.get_user_info
    original_assets = GuangYaClient.get_assets
    original_iter_groups = GuangYaFolderStreamMixin._iter_folder_groups
    original_scan = GuangYaFolderStreamMixin.run_organize_monitor_scan

    def get_user_info(client: GuangYaClient) -> Dict[str, Any]:
        return _cached_control_call(client, "user_info", lambda: original_user_info(client))

    def get_assets(client: GuangYaClient) -> Dict[str, Any]:
        return _cached_control_call(client, "assets", lambda: original_assets(client))

    def iter_groups(plugin: Any, root_path: str, scan_meta: Dict[str, Any]):
        before = _api_network_status(plugin)
        if not before.get("available", True):
            scan_meta["truncated"] = True
            scan_meta["network_deferred"] = True
            scan_meta["network_retry_after"] = _network_retry_after(before)
            return

        try:
            for group in original_iter_groups(plugin, root_path, scan_meta):
                current = _api_network_status(plugin)
                if not current.get("available", True):
                    # 当前 group 可能只扫描了一部分，绝不能把它交给后续状态机。
                    scan_meta["truncated"] = True
                    scan_meta["network_deferred"] = True
                    scan_meta["network_retry_after"] = _network_retry_after(current)
                    return
                yield group
        except Exception:
            current = _api_network_status(plugin)
            if not current.get("available", True):
                # 例如 get_item/list 因 DNS 失败返回空后触发“目录不存在”；网络已明确异常时
                # 将其视为安全延后，而不是目录真的被删除。
                scan_meta["truncated"] = True
                scan_meta["network_deferred"] = True
                scan_meta["network_retry_after"] = _network_retry_after(current)
                return
            raise

        after = _api_network_status(plugin)
        if not after.get("available", True):
            scan_meta["truncated"] = True
            scan_meta["network_deferred"] = True
            scan_meta["network_retry_after"] = _network_retry_after(after)

    def run_scan(plugin: Any, manual: bool = False) -> Dict[str, Any]:
        before = _api_network_status(plugin)
        if not before.get("available", True):
            retry_after = max(int(_network_retry_after(before)), 1)
            status = plugin._save_monitor_status(
                scan_in_progress=False,
                network_deferred=True,
                network_retry_after=retry_after,
                network_message="光鸭文件 API DNS/连接暂不可用，自动整理已安全延后",
            )
            return {
                "success": True,
                "message": f"光鸭网络/DNS暂不可用，本轮扫描已安全延后，约 {retry_after}s 后自动重试",
                "data": status,
            }

        result = original_scan(plugin, manual=manual)
        after = _api_network_status(plugin)
        if not after.get("available", True):
            retry_after = max(int(_network_retry_after(after)), 1)
            status = plugin._save_monitor_status(
                network_deferred=True,
                network_retry_after=retry_after,
                network_message="扫描期间光鸭文件 API 网络中断；本轮 inventory 已按截断处理，不清理旧状态",
            )
            if isinstance(result, dict):
                result["success"] = True
                result["message"] = (
                    f"扫描期间检测到光鸭网络/DNS中断，本轮已安全停止并保留已有状态，"
                    f"约 {retry_after}s 后自动重试"
                )
                result["data"] = status
            return result

        plugin._save_monitor_status(
            network_deferred=False,
            network_retry_after=0,
            network_message="",
        )
        return result

    GuangYaClient._request = _request
    GuangYaClient.get_user_info = get_user_info
    GuangYaClient.get_assets = get_assets
    GuangYaClient.get_network_status = _network_status

    GuangYaFolderStreamMixin._iter_folder_groups = iter_groups
    GuangYaFolderStreamMixin.run_organize_monitor_scan = run_scan

    GuangYaClient._guangya_network_resilience_v347 = True


__all__ = ["install_network_resilience_v347"]
