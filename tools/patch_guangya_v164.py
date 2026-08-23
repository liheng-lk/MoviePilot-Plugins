from pathlib import Path
import json

ROOT = Path('.')
SRC = ROOT / 'plugins.v3' / 'guangyatransferassistant' / '__init__.py'
TEST = ROOT / 'tests' / 'v3' / 'guangyatransferassistant' / 'test_plugin_contract.py'
PACKAGE = ROOT / 'package.v3.json'
PLUGIN = ROOT / 'plugins.v3' / 'guangyatransferassistant' / 'plugin.json'

text = SRC.read_text(encoding='utf-8')

def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'{label} anchor not found')
    text = text.replace(old, new, 1)

replace_once('    plugin_version = "1.6.3"\n', '    plugin_version = "1.6.4"\n', 'plugin version')
replace_once('    _data_schema_version = 6\n', '    _data_schema_version = 6\n    _startup_pending = False\n', 'startup flag')

old_init_tail = '''        if self._enabled:\n            self._install_takeover()\n\n    def get_state(self) -> bool:\n'''
new_init_tail = '''        self._startup_pending = bool(self._enabled)\n        cached_count = len(((self.get_data("channel_index") or {}).get("items") or []))\n        self._plugin_log(\n            "INFO",\n            "【光鸭转存助手】【启动】v%s 启用=%s 自动转存=%s 刷新周期=%s分钟 固定转存订阅=%s 缓存索引=%s",\n            self.plugin_version, self._enabled, self._auto_transfer_on_refresh, self._refresh_minutes,\n            len(self._selected_subscriptions), cached_count,\n        )\n        if self._enabled:\n            self._install_takeover()\n\n    def get_state(self) -> bool:\n'''
replace_once(old_init_tail, new_init_tail, 'startup log')

old_service = '''    def get_service(self) -> List[Dict[str, Any]]:\n        if not self._enabled:\n            return []\n        services: List[Dict[str, Any]] = [{\n            "id": "GuangYaTransferAssistantTick",\n            "name": "光鸭转存助手频道刷新与路由守护",\n            "trigger": "interval",\n            "func": self._tick,\n            "kwargs": {"minutes": self._refresh_minutes},\n        }]\n'''
new_service = '''    def get_service(self) -> List[Dict[str, Any]]:\n        if not self._enabled:\n            return []\n        services: List[Dict[str, Any]] = []\n        if self._startup_pending:\n            self._startup_pending = False\n            services.append({\n                "id": "GuangYaTransferAssistantStartup",\n                "name": "光鸭转存助手启动缓存检查",\n                "trigger": "date",\n                "func": self._startup_check,\n                "kwargs": {},\n            })\n        services.append({\n            "id": "GuangYaTransferAssistantTick",\n            "name": "光鸭转存助手频道增量刷新与路由守护",\n            "trigger": "interval",\n            "func": self._tick,\n            "kwargs": {"minutes": self._refresh_minutes},\n        })\n'''
replace_once(old_service, new_service, 'startup service')

old_manual_guard_end = '''        return None\n\n    def get_api(self) -> List[Dict[str, Any]]:\n'''
new_manual_guard_end = '''        return None\n\n    def _cached_matches_for_subscription(self, subscribe: Any) -> List[Tuple[Dict[str, Any], str]]:\n        \"\"\"从本地频道索引直接取该订阅的已知分享；stale 只代表频道抓取失败，不代表光鸭分享失效。\"\"\"\n        entries = list(((self.get_data("channel_index") or {}).get("items") or []))\n        pairs: List[Tuple[Dict[str, Any], str]] = []\n        for entry in entries:\n            matched, reason = _entry_match_reason(entry, subscribe)\n            if matched and entry.get("share_url"):\n                pairs.append((entry, reason))\n        return pairs\n\n    def _prepare_cache_first_manual_check(self, subscribe: Any, action: str) -> List[Tuple[Dict[str, Any], str]]:\n        sid = int(getattr(subscribe, "id", 0) or 0)\n        pairs = self._cached_matches_for_subscription(subscribe)\n        if pairs:\n            fallback = sum(1 for entry, _ in pairs if entry.get("stale"))\n            self._plugin_log(\n                "INFO", "【光鸭转存助手】【缓存命中】%s #%s %s 命中本地索引 %s 个分享（故障缓存 %s）；不访问 Telegram，直接检查光鸭分享",\n                action, sid, getattr(subscribe, "name", ""), len(pairs), fallback,\n            )\n            return pairs\n        self._plugin_log(\n            "INFO", "【光鸭转存助手】【缓存未命中】%s #%s %s 本地索引没有可匹配分享，执行一次频道增量刷新",\n            action, sid, getattr(subscribe, "name", ""),\n        )\n        self.refresh_channels(force=True)\n        pairs = self._cached_matches_for_subscription(subscribe)\n        self._plugin_log(\n            "INFO", "【光鸭转存助手】【频道增量刷新】%s #%s %s 刷新后匹配分享=%s",\n            action, sid, getattr(subscribe, "name", ""), len(pairs),\n        )\n        return pairs\n\n    def get_api(self) -> List[Dict[str, Any]]:\n'''
replace_once(old_manual_guard_end, new_manual_guard_end, 'cache helpers')

replace_once(
    '{"path": "/check_missing", "endpoint": self.api_check_missing, "methods": ["POST"], "summary": "立即刷新并检查指定转存订阅缺集"},',
    '{"path": "/check_missing", "endpoint": self.api_check_missing, "methods": ["POST"], "summary": "缓存优先检查指定转存订阅缺集"},',
    'api summary',
)

old_api_transfer = '''    def api_transfer(self, payload: dict) -> Dict[str, Any]:\n        payload = payload or {}\n        sid = int(payload.get("subscribe_id") or 0)\n        if not sid:\n            return {"success": False, "message": "subscribe_id 不能为空"}\n        subscribe = self._find_subscription(sid)\n        if not subscribe:\n            return {"success": False, "message": "订阅不存在"}\n        guard = self._manual_transfer_guard(subscribe)\n        if guard:\n            return guard\n        return self._try_transfer_subscription(subscribe, force=True)\n'''
new_api_transfer = '''    def api_transfer(self, payload: dict) -> Dict[str, Any]:\n        payload = payload or {}\n        sid = int(payload.get("subscribe_id") or 0)\n        if not sid:\n            return {"success": False, "message": "subscribe_id 不能为空"}\n        subscribe = self._find_subscription(sid)\n        if not subscribe:\n            return {"success": False, "message": "订阅不存在"}\n        self._plugin_log("INFO", "【光鸭转存助手】【人工检查】立即转存 #%s %s 开始", sid, getattr(subscribe, "name", ""))\n        guard = self._manual_transfer_guard(subscribe)\n        if guard:\n            self._plugin_log("WARNING", "【光鸭转存助手】【门禁】立即转存 #%s %s 拒绝：%s", sid, getattr(subscribe, "name", ""), guard.get("message") or "未知原因")\n            return guard\n        self._prepare_cache_first_manual_check(subscribe, "立即转存")\n        self._inspect_cache.clear()\n        return self._try_transfer_subscription(subscribe, force=True, refresh_channel=False)\n'''
replace_once(old_api_transfer, new_api_transfer, 'api transfer cache first')

old_check_missing = '''    def api_check_missing(self, subscribe_id: int = 0) -> Dict[str, Any]:\n        \"\"\"手动强制刷新频道并只检查该转存订阅当前缺失集。\"\"\"\n        sid = int(subscribe_id or 0)\n        subscribe = self._find_subscription(sid)\n        if not sid or not subscribe:\n            return {"success": False, "message": "订阅不存在"}\n        guard = self._manual_transfer_guard(subscribe)\n        if guard:\n            return guard\n        self.refresh_channels(force=True)\n        self._inspect_cache.clear()\n        result = self._try_transfer_subscription(subscribe, force=True)\n        missing = self._subscription_missing_episodes(self._find_subscription(sid) or subscribe)\n        result["missing_episodes"] = missing\n        return result\n'''
new_check_missing = '''    def api_check_missing(self, subscribe_id: int = 0) -> Dict[str, Any]:\n        \"\"\"缓存优先检查缺集：已知分享直接访问光鸭；只有缓存未命中才刷新 Telegram 频道。\"\"\"\n        sid = int(subscribe_id or 0)\n        subscribe = self._find_subscription(sid)\n        if not sid or not subscribe:\n            return {"success": False, "message": "订阅不存在"}\n        self._plugin_log("INFO", "【光鸭转存助手】【人工检查】立即检查缺集 #%s %s 开始", sid, getattr(subscribe, "name", ""))\n        guard = self._manual_transfer_guard(subscribe)\n        if guard:\n            self._plugin_log("WARNING", "【光鸭转存助手】【门禁】立即检查缺集 #%s %s 拒绝：%s", sid, getattr(subscribe, "name", ""), guard.get("message") or "未知原因")\n            return guard\n        self._prepare_cache_first_manual_check(subscribe, "立即检查缺集")\n        self._inspect_cache.clear()\n        result = self._try_transfer_subscription(subscribe, force=True, refresh_channel=False)\n        missing = self._subscription_missing_episodes(self._find_subscription(sid) or subscribe)\n        result["missing_episodes"] = missing\n        return result\n'''
replace_once(old_check_missing, new_check_missing, 'check missing cache first')

old_tick = '''    def _tick(self) -> None:\n        self._install_takeover()\n        items = self.refresh_channels(force=True)\n        # 分享内容可能在同一个 URL 内热更，每轮正式检查前清掉 API 文件缓存。\n        self._inspect_cache.clear()\n        if self._auto_transfer_on_refresh and any(not item.get("stale") for item in items):\n            self._process_selected_subscriptions(trigger="频道定时刷新")\n\n    def _process_selected_subscriptions(self, trigger: str = "后台检查") -> List[Dict[str, Any]]:\n'''
new_tick = '''    def _startup_check(self) -> None:\n        \"\"\"启动后先消费本地索引，不等待首个 interval；随后再按游标做一次到期增量发现。\"\"\"\n        cached = list(((self.get_data("channel_index") or {}).get("items") or []))\n        self._plugin_log("INFO", "【光鸭转存助手】【启动检查】缓存索引=%s，固定转存订阅=%s", len(cached), len(self._selected_subscriptions))\n        if self._auto_transfer_on_refresh and cached:\n            self._inspect_cache.clear()\n            self._process_selected_subscriptions(trigger="启动缓存检查", refresh_channel=False)\n        before_new = int((self.get_data("channel_index") or {}).get("new_count") or 0)\n        refreshed = self.refresh_channels(force=False)\n        after_new = int((self.get_data("channel_index") or {}).get("new_count") or 0)\n        if self._auto_transfer_on_refresh and refreshed and after_new > 0 and (not cached or after_new != before_new):\n            self._inspect_cache.clear()\n            self._process_selected_subscriptions(trigger="启动频道增量刷新", refresh_channel=False)\n\n    def _tick(self) -> None:\n        self._install_takeover()\n        items = self.refresh_channels(force=False)\n        # 频道负责发现，缓存负责执行；Telegram 故障时已有分享仍可直接访问光鸭。\n        self._inspect_cache.clear()\n        if self._auto_transfer_on_refresh and items:\n            self._process_selected_subscriptions(trigger="频道定时增量刷新", refresh_channel=False)\n\n    def _process_selected_subscriptions(self, trigger: str = "后台检查", refresh_channel: bool = False) -> List[Dict[str, Any]]:\n'''
replace_once(old_tick, new_tick, 'tick cache first')
replace_once(
    '                    result = self._try_transfer_subscription(subscribe)\n                    results.append({"subscribe_id": int(sid), **result})\n',
    '                    result = self._try_transfer_subscription(subscribe, refresh_channel=refresh_channel)\n                    results.append({"subscribe_id": int(sid), **result})\n',
    'process selected refresh param',
)

replace_once(
    '    def _try_transfer_subscription(self, subscribe: Any, force: bool = False) -> Dict[str, Any]:\n',
    '    def _try_transfer_subscription(self, subscribe: Any, force: bool = False, refresh_channel: bool = True) -> Dict[str, Any]:\n',
    'try transfer signature',
)
replace_once(
    '            return self._try_transfer_subscription_inner(subscribe, force=force)\n',
    '            return self._try_transfer_subscription_inner(subscribe, force=force, refresh_channel=refresh_channel)\n',
    'inner call param',
)
replace_once(
    '    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False) -> Dict[str, Any]:\n',
    '    def _try_transfer_subscription_inner(self, subscribe: Any, force: bool = False, refresh_channel: bool = True) -> Dict[str, Any]:\n',
    'inner signature',
)
replace_once(
    '        self.refresh_channels(force=False)\n        # 先把旧版库存迁移成媒体语义事实，再同步事实和 MoviePilot 媒体库。\n',
    '        if refresh_channel:\n            self.refresh_channels(force=False)\n        # 先把旧版库存迁移成媒体语义事实，再同步事实和 MoviePilot 媒体库。\n',
    'conditional channel refresh',
)

old_match_loop = '''        matched_pairs = []\n        stale_matches = 0\n        for item in entries:\n            matched, reason = _entry_match_reason(item, subscribe)\n            if not matched:\n                continue\n            if item.get("stale"):\n                stale_matches += 1\n                continue\n            matched_pairs.append((item, reason))\n        if not matched_pairs:\n            detail = "仅命中故障回退索引，等待频道恢复" if stale_matches else "频道暂未匹配到光鸭分享"\n            self._plugin_log("INFO", "【光鸭转存助手】【匹配】#%s %s %s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), detail)\n            return {"success": False, "handled": True, "message": detail}\n        self._plugin_log("INFO", "【光鸭转存助手】【匹配】#%s %s 命中 %s 个当前频道分享", sid, getattr(subscribe, "name", ""), len(matched_pairs))\n'''
new_match_loop = '''        matched_pairs = []\n        fallback_cache_matches = 0\n        for item in entries:\n            matched, reason = _entry_match_reason(item, subscribe)\n            if not matched:\n                continue\n            if item.get("stale"):\n                fallback_cache_matches += 1\n            matched_pairs.append((item, reason))\n        if not matched_pairs:\n            detail = "本地频道索引暂未匹配到光鸭分享"\n            self._plugin_log("INFO", "【光鸭转存助手】【匹配】#%s %s %s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), detail)\n            return {"success": False, "handled": True, "message": detail}\n        self._plugin_log("INFO", "【光鸭转存助手】【匹配】#%s %s 命中 %s 个缓存/当前分享", sid, getattr(subscribe, "name", ""), len(matched_pairs))\n        if fallback_cache_matches:\n            self._plugin_log(\n                "WARNING", "【光鸭转存助手】【缓存回退】#%s %s 有 %s 个分享来自 Telegram 故障缓存；频道不可用不阻断已知光鸭链接转存",\n                sid, getattr(subscribe, "name", ""), fallback_cache_matches,\n            )\n'''
replace_once(old_match_loop, new_match_loop, 'allow stale cache transfer')

SRC.write_text(text, encoding='utf-8')

# Metadata
plugin = json.loads(PLUGIN.read_text(encoding='utf-8'))
plugin['version'] = '1.6.4'
plugin['description'] = '缓存优先转存：已知频道资源直接使用本地索引访问光鸭分享，Telegram 仅负责增量发现；修复故障缓存有资源却不转存，并增加启动立即检查和完整门禁日志。'
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

package = json.loads(PACKAGE.read_text(encoding='utf-8'))
row = package['GuangYaTransferAssistant']
row['version'] = '1.6.4'
row['description'] = '光鸭订阅固定分流：缓存优先执行，频道只做增量发现；Telegram 故障时已知分享仍可转存，并修复有资源但被 stale 缓存阻断的问题。'
history = row.setdefault('history', {})
history['v1.6.4'] = 'Cache-First：立即检查/立即转存优先使用本地频道索引，只有缓存未命中才访问 Telegram；定时任务取消 force 全量刷新并按游标增量发现；故障回退索引中的已知光鸭链接允许继续转存；插件启动后立即执行一次缓存检查；人工检查、门禁、缓存命中/未命中、频道增量和缓存回退均写入插件日志。'
# newest first
row['history'] = {'v1.6.4': history.pop('v1.6.4'), **history}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# Tests: align existing version expectations and add cache-first contracts.
test = TEST.read_text(encoding='utf-8')
test = test.replace('1.6.3', '1.6.4')
if 'def test_v164_cache_first_execution_contracts()' not in test:
    test += r'''


def test_v164_cache_first_execution_contracts():
    assert 'plugin_version = "1.6.4"' in text
    assert '_cached_matches_for_subscription' in text
    assert '_prepare_cache_first_manual_check' in text
    assert '【光鸭转存助手】【缓存命中】' in text
    assert '【光鸭转存助手】【缓存未命中】' in text
    assert '【光鸭转存助手】【缓存回退】' in text
    assert '频道不可用不阻断已知光鸭链接转存' in text

    manual = text.split('    def api_check_missing(', 1)[1].split('    def api_recheck_pending(', 1)[0]
    cache_pos = manual.index('_prepare_cache_first_manual_check')
    transfer_pos = manual.index('_try_transfer_subscription')
    assert cache_pos < transfer_pos
    assert 'refresh_channels(force=True)' not in manual
    assert 'refresh_channel=False' in manual

    tick = text.split('    def _tick(', 1)[1].split('    def _process_selected_subscriptions(', 1)[0]
    assert 'refresh_channels(force=False)' in tick
    assert 'refresh_channels(force=True)' not in tick
    assert 'refresh_channel=False' in tick

    flow = text.split('    def _try_transfer_subscription_inner(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'if refresh_channel:' in flow
    assert 'fallback_cache_matches' in flow
    assert '仅命中故障回退索引，等待频道恢复' not in flow

    service = text.split('    def get_service(', 1)[1].split('    def get_form(', 1)[0]
    assert 'GuangYaTransferAssistantStartup' in service
    assert '"trigger": "date"' in service
    assert '_startup_check' in text
'''
TEST.write_text(test, encoding='utf-8')

print('GuangYa v1.6.4 cache-first patch applied')
