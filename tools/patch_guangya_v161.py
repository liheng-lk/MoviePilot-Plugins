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


replace_once('    plugin_version = "1.6.0"\n', '    plugin_version = "1.6.1"\n', 'plugin version')

old_sync = '''        sid = int(getattr(subscribe, "id", 0) or 0)\n        media_type = str(getattr(subscribe, "type", "") or "").lower()\n        season = getattr(subscribe, "season", None)\n        if not sid or ("tv" not in media_type and "电视剧" not in str(getattr(subscribe, "type", "") or "") and season in (None, 0)):\n            return {"success": True, "existing": [], "missing": []}\n        try:\n            season = int(season or 0)\n            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))\n            total = int(getattr(subscribe, "total_episode", 0) or 0)\n        except (TypeError, ValueError):\n            return {"success": False, "existing": [], "missing": []}\n        if season <= 0 or total < start:\n            return {"success": False, "existing": [], "missing": []}\n'''
new_sync = '''        sid = int(getattr(subscribe, "id", 0) or 0)\n        raw_type = str(getattr(subscribe, "type", "") or "")\n        media_type = raw_type.lower()\n        raw_season = getattr(subscribe, "season", None)\n        is_tv = "tv" in media_type or "电视剧" in raw_type or raw_season not in (None, "")\n        if not sid or not is_tv:\n            return {"success": True, "existing": [], "missing": []}\n        if raw_season in (None, ""):\n            return {"success": False, "existing": [], "missing": []}\n        try:\n            season = int(raw_season)\n            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))\n            total = int(getattr(subscribe, "total_episode", 0) or 0)\n        except (TypeError, ValueError):\n            return {"success": False, "existing": [], "missing": []}\n        # Season 0 是 MoviePilot 合法的特别篇季；只有负季号或无有效目标集时拒绝同步。\n        if season < 0 or total < start:\n            return {"success": False, "existing": [], "missing": []}\n'''
replace_once(old_sync, new_sync, 'Season 0 library sync')

api_marker = '    def get_api(self) -> List[Dict[str, Any]]:\n'
if api_marker not in text:
    raise SystemExit('get_api marker not found')
helper = '''    def _manual_transfer_guard(self, subscribe: Any) -> Optional[Dict[str, Any]]:\n        """所有会触发转存提交的人工入口共用同一门禁，避免绕过固定分流和待落盘保护。"""\n        sid = int(getattr(subscribe, "id", 0) or 0)\n        if not sid:\n            return {"success": False, "message": "订阅不存在"}\n        if sid not in set(self._selected_subscriptions):\n            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}\n        state = str(getattr(subscribe, "state", "") or "")\n        if state not in ("N", "R"):\n            return {"success": False, "message": f"订阅当前状态 {state or '-'}，不允许人工触发转存"}\n        pending = self._pending_jobs_for_subscription(subscribe)\n        if pending:\n            return {\n                "success": False, "pending": True,\n                "message": f"仍有 {len(pending)} 个已提交任务等待落盘确认；请先使用‘复查待落盘’，不会强制重复提交",\n            }\n        return None\n\n'''
text = text.replace(api_marker, helper + api_marker, 1)

# Mutating/manual-action APIs use POST; folders remains read-only GET.
for old, new in [
    ('{"path": "/check_missing", "endpoint": self.api_check_missing, "methods": ["GET"]', '{"path": "/check_missing", "endpoint": self.api_check_missing, "methods": ["POST"]'),
    ('{"path": "/release_native", "endpoint": self.api_release_native, "methods": ["GET"]', '{"path": "/release_native", "endpoint": self.api_release_native, "methods": ["POST"]'),
    ('{"path": "/recheck_pending", "endpoint": self.api_recheck_pending, "methods": ["GET"]', '{"path": "/recheck_pending", "endpoint": self.api_recheck_pending, "methods": ["POST"]'),
    ('{"path": "/reset_state", "endpoint": self.api_reset_state, "methods": ["GET"]', '{"path": "/reset_state", "endpoint": self.api_reset_state, "methods": ["POST"]'),
    ('{"path": "/cancel_pending", "endpoint": self.api_cancel_pending, "methods": ["GET"]', '{"path": "/cancel_pending", "endpoint": self.api_cancel_pending, "methods": ["POST"]'),
    ('{"path": "/daily_summary", "endpoint": self.api_daily_summary, "methods": ["GET"]', '{"path": "/daily_summary", "endpoint": self.api_daily_summary, "methods": ["POST"]'),
]:
    if old not in text:
        raise SystemExit(f'api method anchor not found: {old}')
    text = text.replace(old, new, 1)

# Internal page buttons follow the hardened POST APIs.
for endpoint in ('check_missing', 'release_native', 'recheck_pending', 'reset_state', 'cancel_pending'):
    old = f'"api": "plugin/GuangYaTransferAssistant/{endpoint}", "method": "get"'
    new = f'"api": "plugin/GuangYaTransferAssistant/{endpoint}", "method": "post"'
    if old not in text:
        raise SystemExit(f'page event anchor not found: {endpoint}')
    text = text.replace(old, new)

old_transfer = '''        subscribe = self._find_subscription(sid)\n        if not subscribe:\n            return {"success": False, "message": "订阅不存在"}\n        return self._try_transfer_subscription(subscribe, force=True)\n'''
new_transfer = '''        subscribe = self._find_subscription(sid)\n        if not subscribe:\n            return {"success": False, "message": "订阅不存在"}\n        guard = self._manual_transfer_guard(subscribe)\n        if guard:\n            return guard\n        return self._try_transfer_subscription(subscribe, force=True)\n'''
replace_once(old_transfer, new_transfer, 'api_transfer guard')

old_check = '''        if sid not in set(self._selected_subscriptions):\n            return {"success": False, "message": "该订阅当前不是光鸭固定转存路线"}\n        pending = self._pending_jobs_for_subscription(subscribe)\n        if pending:\n            return {\n                "success": False, "pending": True,\n                "message": f"仍有 {len(pending)} 个已提交任务等待落盘确认；请先使用‘复查待落盘’，不会强制重复提交",\n            }\n        self.refresh_channels(force=True)\n'''
new_check = '''        guard = self._manual_transfer_guard(subscribe)\n        if guard:\n            return guard\n        self.refresh_channels(force=True)\n'''
replace_once(old_check, new_check, 'api_check_missing guard')

SRC.write_text(text, encoding='utf-8')

package = json.loads(PACKAGE.read_text(encoding='utf-8'))
entry = package['GuangYaTransferAssistant']
entry['version'] = '1.6.1'
entry['description'] = '光鸭订阅固定分流：补齐 S00 媒体库事实同步，统一人工转存防重门禁，并将状态变更接口收敛为 POST；保留 v1.6 任务审计/在途预留/日报与完整可靠性闭环。'
history = entry.setdefault('history', {})
history = {'v1.6.1': '稳定性补丁：修复 Season 0/特别篇订阅无法从 MoviePilot 媒体库同步既有集的问题；所有人工转存入口统一经过固定分流、活跃状态和待落盘任务门禁，避免直接 transfer API 绕过防重保护；检查缺集、复查待落盘、重置、忽略任务、切换普通下载和手动日报等状态变更接口改为 POST。', **history}
entry['history'] = history
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

plugin = json.loads(PLUGIN.read_text(encoding='utf-8'))
plugin['version'] = '1.6.1'
plugin['description'] = '固定转存订阅：S00 媒体库同步、统一人工防重门禁、状态变更 POST 接口，并保留任务审计/在途预留/日报及完整可靠性闭环。'
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

tests = TEST.read_text(encoding='utf-8').replace('1.6.0', '1.6.1')
addition = r'''


def test_v161_season_zero_library_sync_and_manual_gate_contracts():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == "1.6.1" and local["version"] == "1.6.1"
    assert 'plugin_version = "1.6.1"' in text

    sync = text.split('    def _sync_media_library_progress(', 1)[1].split('    def _install_takeover(', 1)[0]
    assert 'raw_season = getattr(subscribe, "season", None)' in sync
    assert 'is_tv =' in sync
    assert 'season = int(raw_season)' in sync
    assert 'if season < 0 or total < start:' in sync
    assert 'if season <= 0' not in sync
    assert 'totals={season: total}' in sync

    guard = text.split('    def _manual_transfer_guard(', 1)[1].split('    def get_api(', 1)[0]
    assert 'sid not in set(self._selected_subscriptions)' in guard
    assert 'state not in ("N", "R")' in guard
    assert '_pending_jobs_for_subscription(subscribe)' in guard
    assert '复查待落盘' in guard

    transfer = text.split('    def api_transfer(', 1)[1].split('    def api_folders(', 1)[0]
    assert '_manual_transfer_guard(subscribe)' in transfer
    assert transfer.index('_manual_transfer_guard(subscribe)') < transfer.index('_try_transfer_subscription(subscribe, force=True)')

    missing = text.split('    def api_check_missing(', 1)[1].split('    def api_recheck_pending(', 1)[0]
    assert '_manual_transfer_guard(subscribe)' in missing
    assert missing.index('_manual_transfer_guard(subscribe)') < missing.index('_try_transfer_subscription(subscribe, force=True)')


def test_v161_mutating_plugin_apis_use_post():
    api = text.split('    def get_api(', 1)[1].split('    def api_refresh(', 1)[0]
    assert '{"path": "/folders", "endpoint": self.api_folders, "methods": ["GET"]' in api
    for endpoint in ('check_missing', 'release_native', 'recheck_pending', 'reset_state', 'cancel_pending', 'daily_summary'):
        assert f'{{"path": "/{endpoint}"' in api
        fragment = api.split(f'{{"path": "/{endpoint}"', 1)[1].split('}', 1)[0]
        assert '"methods": ["POST"]' in fragment
    for endpoint in ('check_missing', 'release_native', 'recheck_pending', 'reset_state', 'cancel_pending'):
        assert f'"api": "plugin/GuangYaTransferAssistant/{endpoint}", "method": "post"' in text
'''
if 'test_v161_season_zero_library_sync_and_manual_gate_contracts' not in tests:
    tests += addition
TEST.write_text(tests, encoding='utf-8')

print('GuangYa v1.6.1 hardening patch applied')
