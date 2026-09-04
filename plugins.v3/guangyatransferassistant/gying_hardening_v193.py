"""v1.9.3 GYING 完整性收口。

在完整 GYING 运行时与故障切换层之前增加最后一层安全/兼容补丁：
- 中文 IDN 与 punycode 统一成同一节点身份，避免重复验证/重复冷却；
- 把当前可访问的中文内容节点作为备用种子，但不写死为唯一入口；
- 手工 Cookie 只发送到与其绑定的首选节点，避免节点切换时跨域携带登录态；
- GYING 搜索在“标题+年份+季”零结果时自动退化到纯标题关键词；
- Provider 候选如果同时有年份信息，年份必须与 MoviePilot 订阅一致；
- 对 Angie/伪 404 等出口阻断做显式失败，让 Failover 立即换节点；
- v1.12.5 追加迅雷召回收口：搜索卡片先按标题/年份/季排序，再开 downurl；同一详情中的
  迅雷分享不再被通用 20 条候选上限截断；严格关键词没有当前订阅可用迅雷时才逐级放宽，
  并优先尝试能直接覆盖真实缺集的分享，避免无意义扩大搜索请求。
"""

from __future__ import annotations

import html
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, quote, urlparse, urlunparse

import requests

from .episode_resolver_v190 import AUTO_SELECT_CONFIDENCE, reliable_episode_set, resolve_episode
from .gying_protocol_v1106 import extract_resource_rows_v1106
from .gying_runtime_v193 import _apply_cookie_header, _parse_search_payload
from .legacy import _normalize_media_text
from .provider_sources_v192 import _proxy_dict


CURRENT_CONTENT_SEEDS = (
    "https://www.星际穿越.com",
)
LEGACY_GYING_DEFAULT = "https://www.gying.org"
_BLOCK_PAGE_MARKERS = (
    "Angie",
    "request forbidden",
    "access denied",
)
_XUNLEI_SHARE_RE_V1125 = re.compile(r"https?://pan\.xunlei\.com/s/[^\s\"'<>，。；;]+", re.I)
_XUNLEI_PASSCODE_RE_V1125 = re.compile(
    r"(?:提取码|访问码|密码|口令|pass\s*code|passcode|pwd)\s*[:：=]?\s*([A-Za-z0-9]{1,16})",
    re.I,
)
_SEASON_EVIDENCE_RE_V1125 = re.compile(
    r"(?i)(?:\bS(?:eason)?[ ._-]*0*(\d{1,2})(?=[^0-9]|$)|第\s*0*(\d{1,2})\s*季)"
)


def canonical_gying_node(value: str) -> str:
    """把中文域名和 punycode 统一成 ASCII 节点身份，同时丢弃路径/凭据。"""
    raw = str(value or "").strip().strip("`\"'()[]{}，。；;")
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    host = parsed.hostname.strip(".")
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.startswith("127.") or lowered.endswith(".local"):
        return ""
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except Exception:
        return ""
    port = parsed.port
    netloc = ascii_host if port is None else f"{ascii_host}:{port}"
    return urlunparse((parsed.scheme.lower(), netloc, "", "", "", "")).rstrip("/")


def gying_keyword_variants(keyword: str) -> List[str]:
    """GYING 对附加年份/季号并不稳定；只在零结果时按从严到宽顺序降级。"""
    original = " ".join(str(keyword or "").split())
    if not original:
        return []
    rows = [original]
    current = re.sub(r"\s+S\d{1,2}\s*$", "", original, flags=re.I).strip()
    if current and current not in rows:
        rows.append(current)
    current = re.sub(r"\s+(?:19|20)\d{2}\s*$", "", current, flags=re.I).strip()
    if current and current not in rows:
        rows.append(current)
    return rows[:3]


def _gying_rank_text_v1125(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _gying_query_identity_v1125(keyword: str) -> Tuple[str, str, int]:
    """解析插件生成的 `标题 年份 Sxx`，避免把《1984》《1899》这种数字片名当年份。"""
    raw = " ".join(str(keyword or "").split())
    season = 0
    season_match = _SEASON_EVIDENCE_RE_V1125.search(raw)
    if season_match:
        for value in season_match.groups():
            if value:
                season = int(value)
                break

    without_season = re.sub(
        r"(?i)\s+(?:S(?:eason)?[ ._-]*0*\d{1,2}(?:[ ._-]*E0*\d{1,4})?|第\s*0*\d{1,2}\s*季)\s*$",
        "",
        raw,
    ).strip()
    year = ""
    title = without_season
    # 年份只认“非空标题 + 末尾 4 位年份”这一结构；单独的 1984/1899 永远保留为片名。
    year_match = re.match(r"^(?P<title>.+?)\s+(?P<year>(?:19|20)\d{2})$", without_season)
    if year_match:
        title = str(year_match.group("title") or "").strip()
        year = str(year_match.group("year") or "").strip()
    return _gying_rank_text_v1125(title), year, season


def _gying_card_score_v1125(keyword: str, item: Dict[str, Any]) -> int:
    """只改变详情展开顺序，不丢弃搜索卡片；目标卡可从第 20 条之后被提前。"""
    expected_title, expected_year, expected_season = _gying_query_identity_v1125(keyword)
    raw_title = str((item or {}).get("title") or "")
    raw_info = str((item or {}).get("info") or "")
    actual_title = _gying_rank_text_v1125(raw_title)
    score = 0
    if expected_title and actual_title:
        if actual_title == expected_title:
            score += 1000
        elif expected_title in actual_title:
            score += 850
        elif len(actual_title) >= 3 and actual_title in expected_title:
            score += 700

    # 排序阶段只把结构化 year 和 info 中的年份当元数据；标题里的 1984/1899 可能就是片名。
    actual_year = str((item or {}).get("year") or "").strip()
    year_evidence = set(re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", raw_info))
    if re.fullmatch(r"(?:19|20)\d{2}", actual_year):
        year_evidence.add(actual_year)
    if expected_year:
        if expected_year in year_evidence:
            score += 120
        elif year_evidence:
            score -= 240

    seasons = {
        int(value)
        for pair in _SEASON_EVIDENCE_RE_V1125.findall(f"{raw_title} {raw_info}")
        for value in pair if value
    }
    if expected_season:
        if expected_season in seasons:
            score += 90
        elif seasons:
            score -= 180
    return score


def rank_gying_cards_v1125(keyword: str, cards: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """稳定排序：高置信目标卡优先，同分保持站点原顺序。"""
    indexed = list(enumerate(list(cards or [])))
    indexed.sort(key=lambda pair: (-_gying_card_score_v1125(keyword, pair[1]), pair[0]))
    return [dict(item or {}) for _, item in indexed]


def _xunlei_candidates_from_rows_v1125(rows: Iterable[Dict[str, Any]], limit: int = 80) -> List[Dict[str, Any]]:
    """从一次 downurl 已返回的数据中完整提取迅雷，不增加观影请求。"""
    dedup: Dict[str, Dict[str, Any]] = {}
    for item in rows or []:
        value = html.unescape(str((item or {}).get("url") or ""))
        for match in _XUNLEI_SHARE_RE_V1125.finditer(value):
            raw_url = match.group(0).rstrip(").]】）}")
            parsed = urlparse(raw_url)
            share_match = re.search(r"^/s/([^/?#]+)", parsed.path or "", re.I)
            if not share_match:
                continue
            share_id = share_match.group(1).strip()
            passcode = str((item or {}).get("passcode") or "").strip()
            if not passcode:
                query = parse_qs(parsed.query or "")
                for key in ("pwd", "passcode", "pass_code", "code"):
                    values = query.get(key) or []
                    if values and str(values[0] or "").strip():
                        passcode = str(values[0]).strip()
                        break
            if not passcode:
                nearby = f"{(item or {}).get('name') or ''} {value}"
                code_match = _XUNLEI_PASSCODE_RE_V1125.search(nearby)
                if code_match:
                    passcode = code_match.group(1).strip()
            row = {
                "type": "xunlei",
                "uri": raw_url,
                "identity": share_id,
                "share_id": share_id,
                "passcode": passcode,
                "name": str((item or {}).get("name") or (item or {}).get("search_title") or "").strip(),
                "search_title": str((item or {}).get("search_title") or "").strip(),
                "year": (item or {}).get("year"),
                "provider": "viewing",
            }
            old = dedup.get(share_id)
            if not old or (not old.get("passcode") and passcode):
                dedup[share_id] = row
    return list(dedup.values())[: max(1, int(limit or 80))]


class GuangYaGyingHardeningMixin:
    """最终 GYING 节点身份、Cookie 边界和搜索降级策略。"""

    build_id = "20260904-r51"

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        super().init_plugin(config)
        preferred = canonical_gying_node(str(getattr(self, "_viewing_base_url", "") or ""))
        # v1.9.2 曾把 gying.org 作为固定默认值；现在它只是换址入口时，不应每轮都被当成
        # 首选内容节点。自动切换开启时把这个旧默认迁移为空，让节点池自行选择。
        if bool(getattr(self, "_viewing_auto_switch", True)) and preferred == canonical_gying_node(LEGACY_GYING_DEFAULT):
            preferred = ""
        self._viewing_base_url = preferred

    def _gying_state(self) -> Dict[str, Any]:
        state = dict(super()._gying_state() or {})
        changed = False
        active = canonical_gying_node(str(state.get("active_node") or ""))
        if active != str(state.get("active_node") or ""):
            state["active_node"] = active
            changed = True

        old_nodes = state.get("nodes") or {}
        if isinstance(old_nodes, dict):
            migrated: Dict[str, Dict[str, Any]] = {}
            for raw_node, raw_row in old_nodes.items():
                node = canonical_gying_node(str(raw_node or ""))
                if not node:
                    changed = True
                    continue
                row = dict(raw_row or {}) if isinstance(raw_row, dict) else {}
                old = migrated.get(node)
                if old:
                    old_ok = float(old.get("last_ok_ts") or 0)
                    new_ok = float(row.get("last_ok_ts") or 0)
                    if new_ok >= old_ok:
                        migrated[node] = row
                    changed = True
                else:
                    migrated[node] = row
                if node != str(raw_node or ""):
                    changed = True
            state["nodes"] = migrated

        discovered = []
        for raw in list(state.get("discovered_nodes") or []):
            node = canonical_gying_node(str(raw or ""))
            if node and node not in discovered:
                discovered.append(node)
            if node != str(raw or ""):
                changed = True
        state["discovered_nodes"] = discovered
        if changed:
            self._save_gying_state(state)
        return state

    def _discover_gying_nodes(self, force: bool = False) -> List[str]:
        base = list(super()._discover_gying_nodes(force=force) or [])
        state = self._gying_state()
        rows: List[str] = []
        for raw in (
            str(state.get("active_node") or ""),
            str(getattr(self, "_viewing_base_url", "") or ""),
            *str(getattr(self, "_viewing_node_urls", "") or "").splitlines(),
            *CURRENT_CONTENT_SEEDS,
            *base,
        ):
            node = canonical_gying_node(str(raw or ""))
            if node and node not in rows:
                rows.append(node)
        if rows != list(state.get("discovered_nodes") or []):
            state["discovered_nodes"] = rows[:30]
            state["discovered_at"] = time.time()
            self._save_gying_state(state)
        return rows[:30]

    def _gying_new_session(self, node: str, saved_cookie: str = "") -> requests.Session:
        """配置 Cookie 只跟随首选节点；运行时持久 Cookie 仍按 node 单独恢复。"""
        node = canonical_gying_node(node)
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "sec-ch-ua": '\"Chromium\";v=\"140\", \"Google Chrome\";v=\"140\", \"Not_A Brand\";v=\"99\"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '\"Windows\"',
        })
        proxies = _proxy_dict(bool(getattr(self, "_provider_proxy", False)))
        if proxies:
            session.proxies.update(proxies)
        if saved_cookie:
            _apply_cookie_header(session, saved_cookie)
        configured_cookie = str(getattr(self, "_viewing_cookie", "") or "").strip()
        preferred = canonical_gying_node(str(getattr(self, "_viewing_base_url", "") or ""))
        if configured_cookie and preferred and node == preferred:
            _apply_cookie_header(session, configured_cookie)
        return session

    def _gying_request(self, session: requests.Session, node: str, method: str, url: str, **kwargs: Any) -> requests.Response:
        response = super()._gying_request(session, node, method, url, **kwargs)
        text = str(response.text or "")
        lowered = text.lower()
        if response.status_code in {403, 404} and any(marker.lower() in lowered for marker in _BLOCK_PAGE_MARKERS):
            raise RuntimeError(f"观影节点当前出口被阻断：HTTP {response.status_code}")
        return response

    def _gying_raw_results(self, keyword: str, force: bool = False):
        variants = gying_keyword_variants(keyword)
        if not variants:
            return super()._gying_raw_results(keyword, force=force)
        last_rows = []
        last_state: Dict[str, Any] = {"success": False, "message": "观影搜索失败"}
        for index, variant in enumerate(variants):
            rows, state = super()._gying_raw_results(variant, force=force)
            last_rows, last_state = rows, dict(state or {})
            if not state.get("success"):
                return rows, state
            if int(state.get("cards") or 0) > 0 or rows:
                if variant != variants[0]:
                    last_state["query_fallback"] = variant
                    last_state["message"] = f"{last_state.get('message') or '观影搜索成功'} · 已自动使用纯标题查询"
                return rows, last_state
        return last_rows, last_state

    def _gying_xunlei_precise_variant_v1125(self, keyword: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """针对一个关键词做一次精准迅雷召回；首轮请求量不高于旧实现。"""
        keyword = " ".join(str(keyword or "").split())
        if not keyword:
            return [], {"provider": "viewing_xunlei", "success": False, "message": "观影搜索关键词为空"}

        cached = dict(getattr(self, "_gying_search_cache", {}).get(keyword) or {})
        cached_state = dict(cached.get("state") or {})
        if (
            cached
            and cached_state.get("recall_ranked_v1125")
            and time.time() - float(cached.get("ts") or 0) < 120
        ):
            rows = list(cached.get("rows") or [])
            limit = max(40, min(120, int(getattr(self, "_provider_result_limit", 20) or 20) * 4))
            return _xunlei_candidates_from_rows_v1125(rows, limit=limit), cached_state

        session, login = self._viewing_session()
        if not login.get("success"):
            return [], {"provider": "viewing_xunlei", **dict(login or {})}
        node = str(
            login.get("node")
            or getattr(self, "_gying_active_node", "")
            or getattr(self, "_viewing_base_url", "")
            or ""
        ).rstrip("/")
        if not node:
            return [], {"provider": "viewing_xunlei", "success": False, "message": "观影没有可用内容节点"}

        try:
            query = quote(keyword, safe="")
            search_variants = [
                ("browser", f"{node}/search?q={query}&type=&mode=1"),
                ("legacy", f"{node}/search?q={query}&type=0&mode=2"),
            ]
            cards: List[Dict[str, Any]] = []
            response = None
            search_mode = "browser"
            for mode, search_url in search_variants:
                current = self._gying_request(
                    session,
                    node,
                    "GET",
                    search_url,
                    headers={"Referer": node + "/"},
                )
                if self._gying_login_required(current):
                    relogin = self._gying_login_password(session, node)
                    if not relogin.get("success"):
                        raise RuntimeError(str(relogin.get("message") or "观影登录失效"))
                    current = self._gying_request(
                        session,
                        node,
                        "GET",
                        search_url,
                        headers={"Referer": node + "/"},
                    )
                if current.status_code >= 400:
                    if mode == "browser":
                        continue
                    raise RuntimeError(f"观影搜索 HTTP {current.status_code}")
                parsed = _parse_search_payload(current.text or "")
                response = current
                search_mode = mode
                if parsed:
                    cards = parsed
                    break
            if response is None:
                raise RuntimeError("观影搜索没有得到有效响应")

            ranked_cards = rank_gying_cards_v1125(keyword, cards)
            detail_limit = max(1, min(int(getattr(self, "_provider_result_limit", 20) or 20), 100))
            detail_cards = ranked_cards[:detail_limit]
            rows: List[Dict[str, Any]] = []
            for item in detail_cards:
                resource_type = str(item.get("type") or "").strip()
                resource_id = str(item.get("id") or "").strip()
                if not resource_type or not resource_id:
                    continue
                detail_referer = f"{node}/{quote(resource_type)}/{quote(resource_id)}"
                try:
                    payload = self._gying_detail(session, node, resource_type, resource_id, detail_referer)
                except Exception as err:
                    logger = getattr(self, "_gying_obs_log", None)
                    if callable(logger):
                        logger(
                            "WARNING",
                            "迅雷召回详情跳过：标题=%s 类型=%s 错误=%s",
                            str(item.get("title") or "-")[:80],
                            resource_type[:24],
                            str(err)[:180],
                        )
                    continue
                rows.extend(extract_resource_rows_v1106(payload, item))

            deduped: List[Dict[str, Any]] = []
            seen = set()
            for row in rows:
                key = (str(row.get("url") or "").strip(), str(row.get("passcode") or "").strip())
                if not key[0] or key in seen:
                    continue
                seen.add(key)
                deduped.append(row)

            xunlei_limit = max(40, min(120, int(getattr(self, "_provider_result_limit", 20) or 20) * 4))
            candidates = _xunlei_candidates_from_rows_v1125(deduped, limit=xunlei_limit)
            self._gying_persist_session(
                node,
                session,
                status="ok",
                login_mode=str(login.get("mode") or ""),
                last_search_at=self._now_text(),
            )
            state = {
                "provider": "viewing_xunlei",
                "success": True,
                "node": node,
                "login_mode": login.get("mode"),
                "cards": len(cards),
                "detail_cards": len(detail_cards),
                "resources": len(deduped),
                "xunlei_resources": len(candidates),
                "search_mode": search_mode,
                "recall_ranked_v1125": True,
                "message": (
                    f"观影迅雷精准搜索：影视 {len(cards)} · 展开 {len(detail_cards)} · 迅雷 {len(candidates)}"
                ),
            }
            # 与 Magnet 复用本次详情结果；后续来源不需要再重复打开同一批 downurl。
            self._gying_search_cache[keyword] = {"ts": time.time(), "rows": deduped, "state": state}
            return candidates, state
        except Exception as err:
            self._gying_mark_node(node, "search_error", str(err))
            return [], {
                "provider": "viewing_xunlei",
                "success": False,
                "node": node,
                "login_mode": login.get("mode"),
                "message": str(err)[:400],
            }

    @staticmethod
    def _xunlei_candidate_priority_v1125(subscribe: Any, row: Dict[str, Any], missing: set[int]) -> Tuple[int, int]:
        if not missing:
            return 0, 0
        label = " ".join(
            str(value or "").strip()
            for value in (row.get("name"), row.get("search_title"))
            if str(value or "").strip()
        )
        try:
            parsed = resolve_episode(label, season_hint=getattr(subscribe, "season", None))
            episodes = reliable_episode_set(parsed, AUTO_SELECT_CONFIDENCE)
        except Exception:
            episodes = set()
        if episodes.intersection(missing):
            return 0, min(episodes.intersection(missing))
        if not episodes:
            return 1, 0
        return 2, min(episodes)

    def _search_viewing_xunlei(self, keyword: str):
        """只在当前订阅没有可用迅雷候选时放宽关键词，不因“搜到别的卡片”提前停止。"""
        variants = gying_keyword_variants(keyword)
        if not variants:
            return super()._search_viewing_xunlei(keyword)
        context = getattr(self, "_gying_xunlei_context_v1125", None)
        subscribe = getattr(context, "subscribe", None) if context is not None else None
        last_state: Dict[str, Any] = {"provider": "viewing_xunlei", "success": False, "message": "观影迅雷搜索失败"}
        for variant in variants:
            candidates, state = self._gying_xunlei_precise_variant_v1125(variant)
            last_state = dict(state or {})
            if not last_state.get("success"):
                return candidates, last_state
            matched = list(candidates or [])
            if subscribe is not None:
                matched = [row for row in matched if self._provider_candidate_matches(subscribe, row)]
            if matched:
                missing: set[int] = set()
                if subscribe is not None and not self._is_movie_subscription(subscribe):
                    try:
                        missing = {
                            int(value)
                            for value in (self._subscription_missing_episodes(subscribe) or [])
                            if int(value or 0) > 0
                        }
                    except Exception:
                        missing = set()
                    matched.sort(key=lambda row: self._xunlei_candidate_priority_v1125(subscribe, row, missing))
                last_state["matched_candidates"] = len(matched)
                if variant != variants[0]:
                    last_state["query_fallback"] = variant
                    last_state["message"] = (
                        f"{last_state.get('message') or '观影迅雷搜索成功'} · 严格关键词无当前订阅可用迅雷，已降级到 {variant}"
                    )
                return matched, last_state
        last_state["searched_variants"] = variants
        last_state["message"] = (
            f"观影可访问，但 {len(variants)} 级关键词均没有当前订阅可用迅雷分享"
            if last_state.get("success") else last_state.get("message")
        )
        return [], last_state

    def _dispatch_xunlei_flash(self, subscribe: Any) -> Dict[str, Any]:
        """给迅雷搜索提供线程隔离的订阅上下文，业务转存仍完全交回原链。"""
        context = getattr(self, "_gying_xunlei_context_v1125", None)
        if context is None:
            context = threading.local()
            self._gying_xunlei_context_v1125 = context
        previous = getattr(context, "subscribe", None)
        context.subscribe = subscribe
        try:
            return super()._dispatch_xunlei_flash(subscribe)
        finally:
            if previous is None:
                try:
                    delattr(context, "subscribe")
                except AttributeError:
                    pass
            else:
                context.subscribe = previous

    @staticmethod
    def _provider_candidate_matches(subscribe: Any, row: Dict[str, Any]) -> bool:
        expected = _normalize_media_text(getattr(subscribe, "name", ""))
        actual = _normalize_media_text(row.get("search_title") or row.get("name") or "")
        if not expected or not actual or not (expected in actual or actual in expected):
            return False
        try:
            expected_year = int(getattr(subscribe, "year", 0) or 0)
        except (TypeError, ValueError):
            expected_year = 0
        try:
            actual_year = int(row.get("year") or 0)
        except (TypeError, ValueError):
            actual_year = 0
        if expected_year and actual_year and expected_year != actual_year:
            return False
        return True


__all__ = [
    "GuangYaGyingHardeningMixin",
    "canonical_gying_node",
    "gying_keyword_variants",
    "rank_gying_cards_v1125",
]
