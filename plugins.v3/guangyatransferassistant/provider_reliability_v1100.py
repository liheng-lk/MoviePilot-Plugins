"""v1.10.0 外部资源搜索可靠性与统一搜索视图。

解决两个长期体验问题：
- 通用 Magnet/ED2K 接口不再只假定一个查询参数；按 provider 类型在 q/kw/keyword/search
  之间做有限、可诊断的兼容尝试，并统一 Bearer/X-API-Key 认证头；
- “观影搜索”不再只展示 Magnet/ED2K。统一搜索同时返回观影迅雷分享、观影 Magnet/ED2K
  以及外部 API 候选，让 UI 和自动分流看到同一套真实来源。

v1.10.3 修复 v1.10.0 重构时的方法名漂移：新版控制台与统一搜索调用
``_parse_provider_defs``，而 v1.9.2 的真实配置解析入口仍叫 ``_provider_api_defs``。
增加兼容桥接后，状态页、资源来源检测和统一搜索重新使用同一份 Magnet/ED2K 配置定义。

v1.12.19 开发阶段增加 Provider 性能、排序与并发状态收口：
- GYING 继续单线程执行，避免节点健康/登录会话被并发放大；
- 独立 Magnet/ED2K API 单次搜索最多 4 路并发，并使用进程级 4 槽 BoundedSemaphore 约束多个订阅同时搜索的总并发；
- executor.map 按配置顺序收敛结果，不让网络返回快慢改变候选先后语义；
- URL 关键词模板只请求一次，不再因 q/keyword/kw/search 变体重复请求同一 URL；
- 普通 API 记住最近 6 小时真正返回过资源的查询参数，下次优先尝试；缓存命中为空仍继续其它参数，不牺牲召回；
- 不再“全局先截断、外层再评分”，而是先汇总单源有界候选池、排序、按 identity 去重，最后截断；
- 同一物理资源的重复候选不再默认“配置靠前者获胜”，而是保留排序更优的来源记录；
- 自动分流已有订阅上下文时，canonical identity 已明确拒绝的候选在最终 limit 前淘汰，避免错误 Magnet 饿死合法 ED2K；
- source store 的 upsert/update/delete 在最终运行时使用同一进程级 RLock，避免多个离线 worker 的 read-modify-write 相互覆盖，也让终态质量学习只观察一次真实迁移；
- 来源失败学习采用高置信归责：真实 task 最终 status=5、resolve 后规则不匹配或无媒体文件才扣来源分；订阅删除、网络/API/目标路径等基础设施失败不污染 provider 质量；
- 任一 API worker 的意外异常只降级该来源，不允许拖垮其它 Provider。
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple
from urllib.parse import quote
from xml.etree import ElementTree

import requests

from .provider_sources_v192 import _dedupe_candidates, _find_links, _proxy_dict


_PROVIDER_API_MAX_WORKERS_V11219 = 4
_PROVIDER_API_GLOBAL_SEMAPHORE_V11219 = threading.BoundedSemaphore(_PROVIDER_API_MAX_WORKERS_V11219)
_PROVIDER_QUERY_HINT_TTL_V11219 = 6 * 60 * 60
_PROVIDER_QUERY_HINT_MAX_V11219 = 100
_PROVIDER_QUERY_HINT_LOCK_V11219 = threading.RLock()
_PROVIDER_QUERY_HINTS_V11219: Dict[str, Dict[str, Any]] = {}
_EXTERNAL_SOURCE_TIER_V11219 = {"magnet": 0, "ed2k": 1}
_SOURCE_STORE_MUTATION_LOCK_V11219 = threading.RLock()


def _nonnegative_int_v11219(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _quality_score_v11219(stats: Dict[str, Any]) -> int:
    success = _nonnegative_int_v11219((stats or {}).get("success"))
    failure = _nonnegative_int_v11219((stats or {}).get("failure"))
    if success + failure <= 0:
        return 0
    posterior = (success + 2.0) / (success + failure + 4.0)
    return max(-100, min(100, int(round((posterior - 0.5) * 200.0))))


def _candidate_rank_key_v11219(
    source_type: str,
    eligible: bool,
    coverage_penalty: int,
    extra_episode_count: int,
    hit_episode_count: int,
    quality_score: int,
    candidate_rank: int,
    original_index: int,
) -> Tuple[int, int, int, int, int, int, int, int]:
    source_tier = _EXTERNAL_SOURCE_TIER_V11219.get(str(source_type or "").strip().lower(), 99)
    return (
        source_tier,
        0 if eligible else 1,
        max(0, int(coverage_penalty or 0)),
        max(0, int(extra_episode_count or 0)),
        -max(0, int(hit_episode_count or 0)),
        -max(-100, min(100, int(quality_score or 0))),
        max(0, int(candidate_rank or 0)),
        max(0, int(original_index or 0)),
    )


def _bounded_ordered_map_v11219(worker: Any, items: List[Any], max_workers: int = _PROVIDER_API_MAX_WORKERS_V11219):
    """有限并发执行，但结果顺序严格跟输入配置一致。"""
    rows = list(items or [])
    if not rows:
        return []
    workers = max(1, min(_nonnegative_int_v11219(max_workers) or 1, _PROVIDER_API_MAX_WORKERS_V11219, len(rows)))
    if workers <= 1:
        return [worker(item) for item in rows]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gy-provider") as executor:
        return list(executor.map(worker, rows))


class GuangYaProviderReliabilityV1100Mixin:
    """最终外部 Provider 搜索、探测和统一搜索 API。"""

    build_id = "20260901-r11"

    def _upsert_source(self, *args: Any, **kwargs: Any):
        """串行化完整 source upsert cooperative chain，避免多 worker 覆盖同一持久化快照。"""
        with _SOURCE_STORE_MUTATION_LOCK_V11219:
            return super()._upsert_source(*args, **kwargs)

    def _update_source(self, source_id: str, **fields: Any):
        """串行化状态迁移；锁覆盖下层终态学习观察，保证同一迁移最多记账一次。"""
        with _SOURCE_STORE_MUTATION_LOCK_V11219:
            return super()._update_source(source_id, **fields)

    def _delete_source(self, source_id: str):
        """删除与 upsert/update 共用一把锁，防止删除被并发旧快照复活。"""
        with _SOURCE_STORE_MUTATION_LOCK_V11219:
            return super()._delete_source(source_id)

    @staticmethod
    def _candidate_failure_is_source_attributable_v11219(row: Dict[str, Any]) -> bool:
        """只让高置信“资源自身失败”进入学习，基础设施/管理故障保持中性。"""
        row = dict(row or {})
        error = str(row.get("last_error") or "").strip()
        task_id = str(row.get("task_id") or "").strip()
        try:
            task_status = int(row.get("task_status"))
        except (TypeError, ValueError):
            task_status = -1

        if task_id and task_status == 5:
            return True
        if error.startswith("订阅规则不匹配："):
            return True
        if "未发现可选的视频或字幕文件" in error:
            return True
        return False

    def _record_candidate_quality_outcome_v11219(self, row: Dict[str, Any], success: bool) -> None:
        """成功总是学习；失败仅在可归责于真实资源时学习。"""
        if bool(success):
            return super()._record_candidate_quality_outcome_v11219(row, True)
        if self._candidate_failure_is_source_attributable_v11219(row):
            return super()._record_candidate_quality_outcome_v11219(row, False)
        try:
            self._plugin_log(
                "DEBUG",
                "【光鸭转存助手】【候选学习v1.12.19】跳过非来源责任失败 source=%s error=%s",
                str((row or {}).get("id") or "")[:80],
                str((row or {}).get("last_error") or "")[:240],
            )
        except Exception:
            pass
        return None

    def _parse_provider_defs(self) -> List[Dict[str, str]]:
        """兼容 v1.10 控制台命名，复用 v1.9.2 唯一的 Provider 配置解析入口。"""
        parser = getattr(self, "_provider_api_defs", None)
        if not callable(parser):
            return []
        rows = parser() or []
        return [dict(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _provider_query_variants(kind: str, keyword: str) -> List[Tuple[str, Dict[str, str]]]:
        kind = str(kind or "json").strip().lower()
        keyword = str(keyword or "").strip()
        if kind == "torznab":
            return [("q", {"t": "search", "q": keyword})]
        if kind == "tgsearch":
            keys = ("kw", "q", "keyword", "search")
        elif kind == "limitless":
            keys = ("keyword", "kw", "q", "search")
        else:
            keys = ("q", "keyword", "kw", "search")
        return [(key, {key: keyword}) for key in keys]

    @staticmethod
    def _provider_query_hint_key_v11219(item: Dict[str, str]) -> str:
        kind = str((item or {}).get("kind") or "json").strip().lower()
        url = str((item or {}).get("url") or "").strip()
        return f"{kind}|{url}"[:1000] if url else ""

    def _provider_query_hint_v11219(self, item: Dict[str, str]) -> str:
        key = self._provider_query_hint_key_v11219(item)
        if not key:
            return ""
        now = time.monotonic()
        with _PROVIDER_QUERY_HINT_LOCK_V11219:
            cached = dict(_PROVIDER_QUERY_HINTS_V11219.get(key) or {})
            try:
                cached_at = float(cached.get("ts") or 0)
            except (TypeError, ValueError):
                cached_at = 0.0
            if not cached or cached_at <= 0 or now - cached_at >= _PROVIDER_QUERY_HINT_TTL_V11219:
                _PROVIDER_QUERY_HINTS_V11219.pop(key, None)
                return ""
            return str(cached.get("param") or "").strip()

    def _remember_provider_query_hint_v11219(self, item: Dict[str, str], param: str) -> None:
        key = self._provider_query_hint_key_v11219(item)
        param = str(param or "").strip()
        if not key or not param or param == "url_template":
            return
        now = time.monotonic()
        with _PROVIDER_QUERY_HINT_LOCK_V11219:
            if key not in _PROVIDER_QUERY_HINTS_V11219 and len(_PROVIDER_QUERY_HINTS_V11219) >= _PROVIDER_QUERY_HINT_MAX_V11219:
                oldest_key = min(
                    _PROVIDER_QUERY_HINTS_V11219,
                    key=lambda value: float((_PROVIDER_QUERY_HINTS_V11219.get(value) or {}).get("ts") or 0),
                )
                _PROVIDER_QUERY_HINTS_V11219.pop(oldest_key, None)
            _PROVIDER_QUERY_HINTS_V11219[key] = {"param": param, "ts": now}

    def _provider_query_variants_for_item_v11219(
        self,
        item: Dict[str, str],
        keyword: str,
    ) -> List[Tuple[str, Dict[str, str]]]:
        url = str((item or {}).get("url") or "").strip()
        if any(marker in url for marker in ("{keyword}", "{query}", "{q}")):
            return [("url_template", {})]
        variants = self._provider_query_variants(str((item or {}).get("kind") or "json"), keyword)
        hint = self._provider_query_hint_v11219(item)
        if not hint:
            return variants
        preferred = [row for row in variants if row[0] == hint]
        remaining = [row for row in variants if row[0] != hint]
        return [*preferred, *remaining] if preferred else variants

    @staticmethod
    def _provider_headers(token: str) -> Dict[str, str]:
        headers = {"Accept": "application/json, application/xml, text/xml, text/plain, */*"}
        raw = str(token or "").strip()
        if not raw:
            return headers
        lowered = raw.lower()
        if lowered.startswith("bearer ") or lowered.startswith("basic "):
            headers["Authorization"] = raw
            return headers
        if lowered.startswith("x-api-key:"):
            headers["X-API-Key"] = raw.split(":", 1)[1].strip()
            return headers
        headers["X-API-Key"] = raw
        headers["Authorization"] = f"Bearer {raw}"
        return headers

    @staticmethod
    def _provider_response_candidates(response: requests.Response, *, kind: str, name: str) -> List[Dict[str, Any]]:
        kind = str(kind or "json").strip().lower()
        candidates: List[Dict[str, Any]] = []
        content_type = str(response.headers.get("Content-Type") or "").lower()

        if kind == "torznab" or "xml" in content_type:
            try:
                root = ElementTree.fromstring(response.text or "")
            except Exception:
                root = None
            if root is not None:
                for item in root.findall(".//item"):
                    title = str(item.findtext("title") or "").strip()
                    payloads: List[Any] = [title, item.findtext("link"), item.findtext("guid")]
                    for enclosure in item.findall("enclosure"):
                        payloads.append(enclosure.attrib.get("url"))
                    for attr in item.findall("{*}attr"):
                        attr_name = str(attr.attrib.get("name") or "").lower()
                        if attr_name in {"magneturl", "magnet", "downloadurl", "download"}:
                            payloads.append(attr.attrib.get("value"))
                    for payload in payloads:
                        candidates.extend(_find_links(payload, name=title, provider=name))
                return _dedupe_candidates(candidates)

        payload: Any
        try:
            payload = response.json()
        except Exception:
            text = str(response.text or "")
            try:
                payload = json.loads(text)
            except Exception:
                payload = text
        return _dedupe_candidates(_find_links(payload, provider=name))

    def _search_api_provider(self, item: Dict[str, str], keyword: str):
        name = str(item.get("name") or "API").strip() or "API"
        kind = str(item.get("kind") or "json").strip().lower()
        url = str(item.get("url") or "").strip()
        token = str(item.get("token") or "").strip()
        if not url:
            return [], {"provider": name, "kind": kind, "success": False, "message": "接口地址为空", "attempts": []}

        session = requests.Session()
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        headers = self._provider_headers(token)
        timeout = int(getattr(self, "_provider_timeout", 15) or 15)
        variants = self._provider_query_variants_for_item_v11219(item, keyword)
        attempts: List[Dict[str, Any]] = []
        had_http_success = False
        last_error = ""

        for key, params in variants[:4]:
            request_url = url
            request_params = dict(params)
            if key == "url_template":
                encoded = quote(str(keyword or "").strip(), safe="")
                request_url = request_url.replace("{keyword}", encoded).replace("{query}", encoded).replace("{q}", encoded)
                request_params = {}
            if kind == "torznab" and token:
                request_params["apikey"] = token
            try:
                response = session.get(
                    request_url,
                    params=request_params,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                )
                status = int(response.status_code or 0)
                if status >= 400:
                    message = f"HTTP {status}"
                    attempts.append({"param": key, "status": status, "count": 0, "ok": False, "message": message})
                    last_error = message
                    if status in {401, 403}:
                        break
                    continue
                had_http_success = True
                rows = self._provider_response_candidates(response, kind=kind, name=name)
                attempts.append({"param": key, "status": status, "count": len(rows), "ok": True})
                if rows:
                    self._remember_provider_query_hint_v11219(item, key)
                    limit = int(getattr(self, "_provider_result_limit", 20) or 20)
                    rows = _dedupe_candidates(rows)[:limit]
                    return rows, {
                        "provider": name,
                        "kind": kind,
                        "success": True,
                        "count": len(rows),
                        "query_param": key,
                        "message": f"{name} 搜索成功，得到 {len(rows)} 个 Magnet/ED2K 候选",
                        "attempts": attempts,
                    }
            except Exception as err:
                last_error = str(err)[:240]
                attempts.append({"param": key, "status": 0, "count": 0, "ok": False, "message": last_error})

        if had_http_success:
            return [], {
                "provider": name,
                "kind": kind,
                "success": True,
                "count": 0,
                "message": f"{name} 接口可访问，但本次没有 Magnet/ED2K 候选",
                "attempts": attempts,
            }
        return [], {
            "provider": name,
            "kind": kind,
            "success": False,
            "count": 0,
            "message": last_error or f"{name} 请求失败",
            "attempts": attempts,
        }

    def _parallel_api_provider_search_v11219(self, keyword: str):
        """只并发彼此独立的 API Provider；单次与跨订阅总并发都不超过 4。"""
        definitions = self._parse_provider_defs()
        if not definitions:
            return [], [], 0

        def worker(item: Dict[str, str]):
            try:
                with _PROVIDER_API_GLOBAL_SEMAPHORE_V11219:
                    rows, state = self._search_api_provider(item, keyword)
                return list(rows or []), dict(state or {})
            except Exception as err:
                return [], {
                    "provider": str(item.get("name") or "API")[:120],
                    "kind": str(item.get("kind") or "json")[:40],
                    "success": False,
                    "count": 0,
                    "message": f"Provider worker 异常：{err}"[:300],
                    "attempts": [],
                }

        workers = min(_PROVIDER_API_MAX_WORKERS_V11219, len(definitions))
        results = _bounded_ordered_map_v11219(worker, definitions, workers)
        rows: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = []
        for found, state in results:
            rows.extend(dict(row) for row in (found or []) if isinstance(row, dict))
            states.append(dict(state or {}))
        return rows, states, workers

    def _rank_provider_pool_v11219(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """自动分流先硬过滤身份，再评分、identity 去重；手工搜索无订阅上下文时保留完整候选。"""
        candidates = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not candidates:
            return []

        quality_key_fn = getattr(self, "_candidate_quality_key_v11219", None)
        quality_snapshot_fn = getattr(self, "_candidate_quality_snapshot_v11219", None)
        local_fn = getattr(self, "_candidate_rank_local_v11219", None)
        episode_hint_fn = getattr(self, "_candidate_episode_hint_v1125", None)
        match_fn = getattr(self, "_provider_candidate_matches", None)
        movie_fn = getattr(self, "_is_movie_subscription", None)
        if not all(callable(fn) for fn in (quality_key_fn, quality_snapshot_fn, local_fn)):
            return _dedupe_candidates(candidates)

        try:
            quality = dict(quality_snapshot_fn() or {})
        except Exception:
            quality = {}
        try:
            local = local_fn()
            subscribe = getattr(local, "subscribe", None)
            uncovered = {
                int(value)
                for value in (getattr(local, "uncovered", set()) or set())
                if str(value).isdigit() and int(value) > 0
            }
        except Exception:
            subscribe = None
            uncovered = set()

        is_movie = bool(subscribe is not None and callable(movie_fn) and movie_fn(subscribe))
        ranked = []
        for index, row in enumerate(candidates):
            eligible = True
            coverage_penalty = 1
            extra_episode_count = 0
            hit_episode_count = 0
            if subscribe is not None and callable(match_fn):
                try:
                    eligible = bool(match_fn(subscribe, row))
                except Exception:
                    eligible = False
                if not eligible:
                    continue
            if eligible and subscribe is not None and not is_movie and uncovered and callable(episode_hint_fn):
                try:
                    explicit = set(episode_hint_fn(subscribe, row) or set())
                except Exception:
                    explicit = set()
                if explicit:
                    hit = explicit.intersection(uncovered)
                    extra = explicit - uncovered
                    hit_episode_count = len(hit)
                    extra_episode_count = len(extra)
                    if hit and not extra:
                        coverage_penalty = 0
                    elif hit:
                        coverage_penalty = 2
                    else:
                        coverage_penalty = 3
            try:
                quality_key = str(quality_key_fn(row) or "")
            except Exception:
                quality_key = ""
            quality_score = _quality_score_v11219(dict(quality.get(quality_key) or {})) if quality_key else 0
            sort_key = _candidate_rank_key_v11219(
                str(row.get("type") or ""),
                eligible,
                coverage_penalty,
                extra_episode_count,
                hit_episode_count,
                quality_score,
                _nonnegative_int_v11219(row.get("candidate_rank")),
                index,
            )
            enriched = dict(row)
            enriched["candidate_score_v11219"] = quality_score
            enriched["candidate_sort_v11219"] = list(sort_key[:-1])
            ranked.append((sort_key, enriched))

        ranked.sort(key=lambda item: item[0])
        return _dedupe_candidates([row for _key, row in ranked])

    def _search_external_providers(self, keyword: str) -> Dict[str, Any]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return {"success": False, "message": "keyword 不能为空", "data": [], "providers": []}

        rows: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = []
        try:
            viewing_rows, viewing_state = self._search_viewing(keyword)
            rows.extend(dict(row) for row in (viewing_rows or []) if isinstance(row, dict))
            states.append(dict(viewing_state or {}))
        except Exception as err:
            states.append({"provider": "viewing", "success": False, "message": f"GYING 搜索异常：{err}"[:300]})

        api_rows, api_states, workers = self._parallel_api_provider_search_v11219(keyword)
        rows.extend(api_rows)
        states.extend(api_states)
        raw_count = len(rows)
        ranked = self._rank_provider_pool_v11219(rows)
        deduped_count = len(ranked)
        limit = max(1, int(getattr(self, "_provider_result_limit", 20) or 20))
        returned = ranked[:limit]
        healthy = any(bool(state.get("success")) for state in states if state.get("enabled", True))
        return {
            "success": healthy,
            "message": f"候选池 {raw_count}，过滤去重排序后 {deduped_count}，返回 {len(returned)} 个 Magnet/ED2K 候选",
            "data": returned,
            "providers": states,
            "candidate_ranking_v11219": True,
            "candidate_pool_v11219": {"raw": raw_count, "deduped": deduped_count, "returned": len(returned)},
            "provider_parallelism_v11219": workers,
        }

    def _unified_provider_search(self, keyword: str) -> Dict[str, Any]:
        keyword = str(keyword or "").strip()
        if not keyword:
            return {"success": False, "keyword": "", "message": "搜索关键词不能为空", "data": [], "xunlei": [], "states": []}

        candidates: List[Dict[str, Any]] = []
        xunlei: List[Dict[str, Any]] = []
        states: List[Dict[str, Any]] = []

        if bool(getattr(self, "_viewing_enabled", False)):
            try:
                viewing_rows, viewing_state = self._search_viewing(keyword)
                candidates.extend(dict(row) for row in (viewing_rows or []) if isinstance(row, dict))
                states.append(dict(viewing_state or {}))
            except Exception as err:
                states.append({"provider": "viewing", "success": False, "message": f"GYING 搜索异常：{err}"[:300]})
            try:
                xunlei_rows, xunlei_state = self._search_viewing_xunlei(keyword)
                xunlei.extend(dict(row) for row in (xunlei_rows or []) if isinstance(row, dict))
                states.append(dict(xunlei_state or {}))
            except Exception as err:
                states.append({"provider": "viewing_xunlei", "success": False, "message": f"迅雷搜索异常：{err}"[:300]})

        api_rows, api_states, workers = self._parallel_api_provider_search_v11219(keyword)
        candidates.extend(api_rows)
        states.extend(api_states)

        raw_count = len(candidates)
        ranked = self._rank_provider_pool_v11219(candidates)
        pool_limit = max(1, int(getattr(self, "_provider_result_limit", 20) or 20) * 3)
        candidates = ranked[:pool_limit]

        xunlei_by_id: Dict[str, Dict[str, Any]] = {}
        for row in xunlei:
            share_id = str(row.get("share_id") or row.get("identity") or "").strip()
            if not share_id:
                continue
            previous = xunlei_by_id.get(share_id)
            if not previous or (not previous.get("passcode") and row.get("passcode")):
                xunlei_by_id[share_id] = dict(row)
        xunlei = list(xunlei_by_id.values())[: max(1, int(getattr(self, "_provider_result_limit", 20) or 20))]

        magnet_count = sum(1 for row in candidates if str(row.get("type") or "") == "magnet")
        ed2k_count = sum(1 for row in candidates if str(row.get("type") or "") == "ed2k")
        healthy = any(bool(state.get("success")) for state in states)
        message = f"搜索完成：迅雷 {len(xunlei)} · Magnet {magnet_count} · ED2K {ed2k_count}"
        return {
            "success": healthy,
            "keyword": keyword,
            "message": message,
            "data": candidates,
            "xunlei": xunlei,
            "counts": {"xunlei": len(xunlei), "magnet": magnet_count, "ed2k": ed2k_count},
            "states": states,
            "candidate_ranking_v11219": True,
            "candidate_pool_v11219": {"raw": raw_count, "deduped": len(ranked), "returned": len(candidates)},
            "provider_parallelism_v11219": workers,
        }

    def api_provider_search(self, keyword: str = "") -> Dict[str, Any]:
        return self._unified_provider_search(keyword)

    def api_provider_test(self) -> Dict[str, Any]:
        states: List[Dict[str, Any]] = []
        keyword = "test"
        selected = set(int(value) for value in (getattr(self, "_selected_subscriptions", []) or []) if int(value or 0) > 0)
        if selected:
            for subscribe in self._list_subscriptions(None):
                if int(getattr(subscribe, "id", 0) or 0) in selected:
                    keyword = self._provider_keyword(subscribe) or str(getattr(subscribe, "name", "") or "test")
                    break

        if bool(getattr(self, "_viewing_enabled", False)):
            try:
                _, login = self._viewing_session()
                states.append({
                    "provider": "viewing",
                    "success": bool(login.get("success")),
                    "node": str(login.get("node") or ""),
                    "login_mode": str(login.get("mode") or ""),
                    "message": str(login.get("message") or "")[:300],
                })
            except Exception as err:
                states.append({"provider": "viewing", "success": False, "message": str(err)[:300]})
        else:
            states.append({"provider": "viewing", "success": True, "enabled": False, "message": "未启用"})

        _rows, api_states, _workers = self._parallel_api_provider_search_v11219(keyword)
        states.extend(api_states)

        overall = all(bool(item.get("success")) for item in states if item.get("enabled") is not False)
        result = {"success": overall, "keyword": keyword, "providers": states, "message": "资源来源检测完成" if overall else "部分资源来源不可用，请查看 providers"}
        self.save_data("provider_test_last", result)
        return result

    def api_provider_search_selected(self) -> Dict[str, Any]:
        selected = set(int(value) for value in (getattr(self, "_selected_subscriptions", []) or []) if int(value or 0) > 0)
        if not selected:
            result = {"success": False, "message": "尚未选择固定走光鸭的 MoviePilot 订阅", "items": []}
            self.save_data("provider_search_last", result)
            return result

        items: List[Dict[str, Any]] = []
        for subscribe in self._list_subscriptions(None):
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid not in selected:
                continue
            keyword = self._provider_keyword(subscribe) or str(getattr(subscribe, "name", "") or "")
            search = self._unified_provider_search(keyword)
            counts = dict(search.get("counts") or {})
            previews: List[Dict[str, Any]] = []
            for row in (search.get("xunlei") or [])[:3]:
                previews.append({"type": "xunlei", "name": str(row.get("name") or row.get("search_title") or "")[:160]})
            for row in (search.get("data") or [])[:5]:
                previews.append({"type": str(row.get("type") or ""), "name": str(row.get("name") or row.get("search_title") or "")[:160]})
            items.append({
                "subscribe_id": sid,
                "name": str(getattr(subscribe, "name", "") or ""),
                "year": str(getattr(subscribe, "year", "") or ""),
                "keyword": keyword,
                "success": bool(search.get("success")),
                "counts": counts,
                "message": str(search.get("message") or "")[:300],
                "preview": previews,
            })
            if len(items) >= 12:
                break

        total = {
            "xunlei": sum(int((item.get("counts") or {}).get("xunlei") or 0) for item in items),
            "magnet": sum(int((item.get("counts") or {}).get("magnet") or 0) for item in items),
            "ed2k": sum(int((item.get("counts") or {}).get("ed2k") or 0) for item in items),
        }
        result = {
            "success": any(bool(item.get("success")) for item in items),
            "message": f"已搜索 {len(items)} 个固定转存订阅：迅雷 {total['xunlei']} · Magnet {total['magnet']} · ED2K {total['ed2k']}",
            "counts": total,
            "items": items,
            "updated_at": self._now_text(),
        }
        self.save_data("provider_search_last", result)
        return result

    def get_api(self):
        apis = list(super().get_api() or [])
        paths = {str(item.get("path") or "") for item in apis if isinstance(item, dict)}
        if "/providers/search/selected" not in paths:
            apis.append({
                "path": "/providers/search/selected",
                "endpoint": self.api_provider_search_selected,
                "methods": ["POST"],
                "summary": "搜索已选择订阅的观影/迅雷/Magnet/ED2K 候选",
            })
        return apis


__all__ = [
    "GuangYaProviderReliabilityV1100Mixin",
    "_bounded_ordered_map_v11219",
    "_candidate_rank_key_v11219",
    "_quality_score_v11219",
]
