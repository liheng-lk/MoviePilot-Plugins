from pathlib import Path

p = Path('plugins.v2/dailynewdrama/__init__.py')
s = p.read_text(encoding='utf-8')

s = s.replace(
    'import datetime\nimport re\nimport uuid\nimport xml.dom.minidom\n',
    'import base64\nimport datetime\nimport hashlib\nimport hmac\nimport re\nimport urllib.parse\nimport uuid\nimport xml.dom.minidom\n',
    1,
)

marker = '\n\ndef _format_air_timing_value(air_date: Optional[datetime.date], today: datetime.date) -> str:\n'
helpers = '''

def _parse_douban_direct_subjects(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把豆瓣 Frodo 即将播出 JSON 转成统一候选字典。"""
    result: List[Dict[str, Any]] = []
    subjects = data.get("subjects") if isinstance(data, dict) else None
    if not isinstance(subjects, list):
        return result
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        title = str(subject.get("title") or "").strip()
        doubanid = str(subject.get("id") or "").strip()
        pubdates = subject.get("pubdate") or []
        pubdate_text = str(pubdates[0] if isinstance(pubdates, list) and pubdates else "").strip()
        date_match = re.search(r"(19\\d{2}|20\\d{2})-(\\d{1,2})-(\\d{1,2})", pubdate_text)
        air_date = ""
        year = None
        if date_match:
            year = int(date_match.group(1))
            try:
                air_date = datetime.date(year, int(date_match.group(2)), int(date_match.group(3))).isoformat()
            except ValueError:
                air_date = ""
        if not year:
            year_match = re.search(r"\\b(19\\d{2}|20\\d{2})\\b", pubdate_text)
            year = int(year_match.group(1)) if year_match else None
        result.append({
            "title": title,
            "doubanid": doubanid,
            "year": year,
            "link": str(subject.get("url") or subject.get("sharing_url") or (f"https://movie.douban.com/subject/{doubanid}/" if doubanid else "")),
            "description": str(subject.get("intro") or subject.get("card_subtitle") or ""),
            "air_date": air_date,
            "rss_pub_date": "",
            "source": "coming",
        })
    return result


def _extract_flaresolverr_response(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """从 FlareSolverr 返回 JSON 中提取页面正文和错误信息。"""
    if not isinstance(data, dict):
        return None, "FlareSolverr 返回非 JSON 对象"
    if str(data.get("status") or "").lower() != "ok":
        return None, str(data.get("message") or "FlareSolverr 请求失败")
    solution = data.get("solution") or {}
    if not isinstance(solution, dict):
        return None, "FlareSolverr solution 无效"
    response = solution.get("response")
    if not isinstance(response, str) or not response.strip():
        return None, "FlareSolverr 未返回页面内容"
    return response, None
'''
if '_parse_douban_direct_subjects' not in s:
    s = s.replace(marker, helpers + marker, 1)

s = s.replace(
    '    _rsshub = "https://rsshub.app"\n    _vote = 0.0\n',
    '    _rsshub = "https://rsshub.app"\n    _flaresolverr_enabled = False\n    _flaresolverr_url = "http://flaresolverr:8191"\n    _vote = 0.0\n',
    1,
)
s = s.replace(
    '        self._rsshub = str(config.get("rsshub") or "https://rsshub.app").rstrip("/")\n        self._include_hot = bool(config.get("include_hot", True))\n',
    '        self._rsshub = str(config.get("rsshub") or "https://rsshub.app").rstrip("/")\n        self._flaresolverr_enabled = bool(config.get("flaresolverr_enabled", False))\n        self._flaresolverr_url = str(config.get("flaresolverr_url") or "http://flaresolverr:8191").rstrip("/")\n        self._include_hot = bool(config.get("include_hot", True))\n',
    1,
)
s = s.replace(
    '{"component": "VTextField", "props": {"model": "rsshub", "label": "RSSHub 地址", "placeholder": "https://rsshub.app"}}',
    '{"component": "VTextField", "props": {"model": "rsshub", "label": "RSSHub 地址（备用）", "placeholder": "https://rsshub.app"}}',
    1,
)
alert_text = '"text": "主源使用豆瓣“即将播出剧集”，按播出日期筛选；可选补充近期已开播的豆瓣热门剧。媒体库已有和 MoviePilot 已订阅内容会自动过滤。通知支持按钮订阅；普通消息渠道可发送 /newdrama_sub 1,3 或 /newdrama_sub 1-3。",'
if alert_text in s and 'model": "flaresolverr_enabled"' not in s:
    row = '''                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [
                                {"component": "VSwitch", "props": {"model": "flaresolverr_enabled", "label": "启用 FlareSolverr 过盾"}}
                            ]},
                            {"component": "VCol", "props": {"cols": 12, "md": 8}, "content": [
                                {"component": "VTextField", "props": {"model": "flaresolverr_url", "label": "FlareSolverr 地址", "placeholder": "http://flaresolverr:8191"}}
                            ]},
                        ],
                    },
'''
    pos = s.index('                    {\n                        "component": "VAlert",', s.index(alert_text) - 300)
    s = s[:pos] + row + s[pos:]
    s = s.replace(alert_text, '"text": "数据源自动降级：豆瓣直连 → RSSHub → FlareSolverr（开启时）。RSSHub 仅作为备用；FlareSolverr 建议与 MoviePilot 放在同一 Docker 网络，地址可填 http://flaresolverr:8191。媒体库已有和 MoviePilot 已订阅内容会自动过滤。",', 1)

s = s.replace(
    '            "rsshub": "https://rsshub.app",\n            "vote": 0,\n',
    '            "rsshub": "https://rsshub.app",\n            "flaresolverr_enabled": False,\n            "flaresolverr_url": "http://flaresolverr:8191",\n            "vote": 0,\n',
    1,
)

start = s.index('    def _fetch_sources(self) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:')
end = s.index('    def _recognize(self, meta: MetaInfo, doubanid: str) -> Optional[MediaInfo]:', start)
replacement = '''    def _fetch_sources(self) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """自动降级获取即将播出与近期热播数据，并记录每一层数据源状态。"""
        items: List[Dict[str, Any]] = []
        status: Dict[str, Dict[str, Any]] = {}

        coming, coming_detail = self._fetch_coming_auto()
        status["即将播出"] = {"ok": bool(coming), "count": len(coming), "error": coming_detail.get("error", ""), "via": coming_detail.get("via", ""), "attempts": coming_detail.get("attempts", [])}
        items.extend(coming)

        if self._include_hot:
            hot_url = f"{self._rsshub}/douban/movie/weekly/tv_hot"
            hot, error, via = self._fetch_rss_with_fallback(hot_url, source="hot")
            status["近期热播"] = {"ok": error is None, "count": len(hot), "error": error or "", "via": via}
            items.extend(hot)
        return items, status

    def _fetch_coming_auto(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """优先豆瓣 Frodo 直连，失败后依次使用 RSSHub 和 FlareSolverr。"""
        attempts: List[str] = []
        direct, error = self._fetch_douban_direct_coming()
        if direct:
            logger.info("【每日新剧助手】【豆瓣直连】获取即将播出成功，共 %s 条", len(direct))
            return direct, {"via": "豆瓣直连", "attempts": attempts}
        attempts.append(f"豆瓣直连: {error or '空数据'}")
        logger.warning("【每日新剧助手】【豆瓣直连】失败: %s", error or "空数据")
        url = f"{self._rsshub}/douban/tv/coming/time/{self._coming_count}"
        rss, rss_error, via = self._fetch_rss_with_fallback(url, source="coming")
        if rss:
            return rss, {"via": via, "attempts": attempts}
        attempts.append(f"{via or 'RSSHub'}: {rss_error or '空数据'}")
        return [], {"via": via or "全部失败", "attempts": attempts, "error": "；".join(attempts)}

    def _fetch_douban_direct_coming(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """使用与 RSSHub 当前实现一致的 Frodo 接口直接获取豆瓣即将播出剧集。"""
        api_url = "https://frodo.douban.com/api/v2/tv/coming_soon"
        api_key = "0dad551ec0f84ed02907ff5c42e8ec70"
        api_secret = "bf7dddc7c9cfe6f7"
        ua = "api-client/1 com.douban.frodo/7.22.0.beta9(231) Android/23 product/Mate 40 vendor/HUAWEI model/Mate 40 brand/HUAWEI rom/android network/wifi platform/AndroidPad"
        ts = datetime.datetime.now().strftime("%Y%m%d")
        path = urllib.parse.urlparse(api_url).path
        raw_sign = f"GET&{urllib.parse.quote(path, safe='')}&{ts}"
        signature = base64.b64encode(hmac.new(api_secret.encode(), raw_sign.encode(), hashlib.sha1).digest()).decode()
        params = {"start": 0, "count": self._coming_count, "sortby": "hot", "os_rom": "android", "apiKey": api_key, "_ts": ts, "_sig": signature}
        try:
            request = RequestUtils(proxies=settings.PROXY) if self._proxy else RequestUtils()
            response = request.get_res(api_url, params=params, headers={"Accept": "application/json", "User-Agent": ua})
            if not response:
                return [], "无响应"
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                return [], f"HTTP {status_code}"
            try:
                data = response.json()
            except Exception as err:
                return [], f"JSON解析失败: {err}"
            subjects = _parse_douban_direct_subjects(data)
            if not subjects:
                details = (data.get("msg") or data.get("message") or data.get("reason")) if isinstance(data, dict) else ""
                return [], f"空数据{': ' + str(details) if details else ''}"
            return subjects, None
        except Exception as err:
            return [], str(err)

    def _fetch_rss_with_fallback(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str], str]:
        """先普通请求 RSSHub，失败后按配置使用 FlareSolverr 过盾。"""
        items, error = self._fetch_rss(url, source=source)
        if items:
            logger.info("【每日新剧助手】【RSSHub】获取成功 %s，共 %s 条", url, len(items))
            return items, None, "RSSHub"
        logger.warning("【每日新剧助手】【RSSHub】失败 %s: %s", url, error or "空数据")
        if not self._flaresolverr_enabled:
            return [], error or "RSSHub 空数据", "RSSHub"
        flare_items, flare_error = self._fetch_rss_via_flaresolverr(url, source=source)
        if flare_items:
            logger.info("【每日新剧助手】【FlareSolverr】过盾成功 %s，共 %s 条", url, len(flare_items))
            return flare_items, None, "FlareSolverr"
        logger.error("【每日新剧助手】【FlareSolverr】失败 %s: %s", url, flare_error or "空数据")
        return [], f"RSSHub={error or '失败'}；FlareSolverr={flare_error or '失败'}", "FlareSolverr"

    def _fetch_rss(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """普通 HTTP 请求并解析一个 RSSHub 豆瓣 RSS 地址。"""
        try:
            request = RequestUtils(proxies=settings.PROXY) if self._proxy else RequestUtils()
            response = request.get_res(url)
            if not response:
                return [], "无响应"
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                return [], f"HTTP {status_code}"
            text = response.text or ""
            lowered = text.lower()
            if "cf-chl-" in lowered or ("cloudflare" in lowered and "challenge" in lowered):
                return [], "检测到 Cloudflare Challenge"
            items = _parse_douban_rss(text, source=source)
            if not items:
                return [], "RSS 解析后为空"
            return items, None
        except Exception as err:
            return [], str(err)

    def _fetch_rss_via_flaresolverr(self, url: str, source: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """通过 FlareSolverr /v1 代请求 RSSHub 并解析返回正文。"""
        endpoint = f"{self._flaresolverr_url}/v1"
        payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
        try:
            response = RequestUtils().post_res(endpoint, json=payload)
            if not response:
                return [], "FlareSolverr 无响应"
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                return [], f"FlareSolverr HTTP {status_code}"
            try:
                data = response.json()
            except Exception as err:
                return [], f"FlareSolverr JSON解析失败: {err}"
            body, error = _extract_flaresolverr_response(data)
            if error:
                return [], error
            try:
                items = _parse_douban_rss(body or "", source=source)
            except Exception as err:
                return [], f"FlareSolverr 返回内容不是有效 RSS: {err}"
            if not items:
                return [], "FlareSolverr 返回 RSS 为空"
            return items, None
        except Exception as err:
            return [], str(err)

'''
s = s[:start] + replacement + s[end:]
p.write_text(s, encoding='utf-8')

tp = Path('tests/test_dailynewdrama_logic.py')
t = tp.read_text(encoding='utf-8')
t = t.replace('        "_format_air_timing_value",\n', '        "_format_air_timing_value",\n        "_parse_douban_direct_subjects",\n        "_extract_flaresolverr_response",\n', 1)
insert = '''
    def test_douban_direct_subject_parser(self):
        parse = HELPERS["_parse_douban_direct_subjects"]
        data = {"subjects": [{"id": "123", "title": "测试新剧", "pubdate": ["2026-08-20(中国大陆)"], "intro": "简介"}]}
        item = parse(data)[0]
        self.assertEqual(item["doubanid"], "123")
        self.assertEqual(item["air_date"], "2026-08-20")
        self.assertEqual(item["year"], 2026)
        self.assertEqual(item["source"], "coming")

    def test_flaresolverr_response_parser(self):
        parse = HELPERS["_extract_flaresolverr_response"]
        body, error = parse({"status": "ok", "solution": {"response": "<rss/>"}})
        self.assertEqual(body, "<rss/>")
        self.assertIsNone(error)
        body, error = parse({"status": "error", "message": "challenge failed"})
        self.assertIsNone(body)
        self.assertIn("challenge failed", error)

    def test_source_fallback_contract(self):
        self.assertIn("_fetch_douban_direct_coming", SOURCE_TEXT)
        self.assertIn("_fetch_rss_with_fallback", SOURCE_TEXT)
        self.assertIn("_fetch_rss_via_flaresolverr", SOURCE_TEXT)
        self.assertIn("flaresolverr_enabled", SOURCE_TEXT)
        self.assertIn("flaresolverr_url", SOURCE_TEXT)
        self.assertIn("豆瓣直连", SOURCE_TEXT)
        self.assertIn("FlareSolverr", SOURCE_TEXT)

'''
needle = '    def test_metadata_is_consistent(self):\n'
if 'test_douban_direct_subject_parser' not in t:
    t = t.replace(needle, insert + needle, 1)
tp.write_text(t, encoding='utf-8')
