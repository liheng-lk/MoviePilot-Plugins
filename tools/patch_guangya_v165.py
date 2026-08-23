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

replace_once('    plugin_version = "1.6.4"\n', '    plugin_version = "1.6.5"\n', 'version')
replace_once(
'''    _data_schema_version = 6\n    _startup_pending = False\n''',
'''    _data_schema_version = 6\n    _runtime_generation = 0\n    _runtime_generation_lock = threading.Lock()\n''',
'runtime attrs')

replace_once(
'''        self._startup_pending = bool(self._enabled)\n        cached_count = len(((self.get_data("channel_index") or {}).get("items") or []))\n''',
'''        cached_count = len(((self.get_data("channel_index") or {}).get("items") or []))\n''',
'remove startup pending')

replace_once(
'''        if self._enabled:\n            self._install_takeover()\n\n    def get_state(self) -> bool:\n''',
'''        if self._enabled:\n            self._install_takeover()\n            self._start_runtime_worker()\n\n    def get_state(self) -> bool:\n''',
'start runtime worker')

old_service = '''    def get_service(self) -> List[Dict[str, Any]]:\n        if not self._enabled:\n            return []\n        services: List[Dict[str, Any]] = []\n        if self._startup_pending:\n            self._startup_pending = False\n            services.append({\n                "id": "GuangYaTransferAssistantStartup",\n                "name": "光鸭转存助手启动缓存检查",\n                "trigger": "date",\n                "func": self._startup_check,\n                "kwargs": {},\n            })\n        services.append({\n            "id": "GuangYaTransferAssistantTick",\n            "name": "光鸭转存助手频道增量刷新与路由守护",\n            "trigger": "interval",\n            "func": self._tick,\n            "kwargs": {"minutes": self._refresh_minutes},\n        })\n'''
new_service = '''    def get_service(self) -> List[Dict[str, Any]]:\n        if not self._enabled:\n            return []\n        services: List[Dict[str, Any]] = [{\n            "id": "GuangYaTransferAssistantTick",\n            "name": "光鸭转存助手频道增量刷新与路由守护",\n            "trigger": "interval",\n            "func": self._tick,\n            "kwargs": {"minutes": self._refresh_minutes},\n        }]\n'''
replace_once(old_service, new_service, 'service registration')

# Insert self-managed runtime worker before _startup_check.
anchor = '''    def _startup_check(self) -> None:\n        \"\"\"启动后先消费本地索引，不等待首个 interval；随后再按游标做一次到期增量发现。\"\"\"\n'''
insert = '''    def _start_runtime_worker(self) -> None:\n        \"\"\"启动内置守护线程。宿主未重新注册 get_service 时仍能立即/周期执行；宿主定时器恢复后自动退居备用。\"\"\"\n        try:\n            old_stop = getattr(self, "_runtime_stop", None)\n            if old_stop is not None:\n                old_stop.set()\n        except Exception:\n            pass\n        with type(self)._runtime_generation_lock:\n            type(self)._runtime_generation += 1\n            generation = type(self)._runtime_generation\n        self._runtime_stop = threading.Event()\n        self._host_tick_heartbeat = 0.0\n        self._runtime_thread = threading.Thread(\n            target=self._runtime_worker_loop,\n            args=(generation,),\n            name="GuangYaTransferAssistantRuntime",\n            daemon=True,\n        )\n        self._runtime_thread.start()\n        self._plugin_log(\n            "INFO",\n            "【光鸭转存助手】【服务】内置运行时守护已启动；无需进入设置页再次保存，宿主服务未注册时自动接管",\n        )\n\n    def _runtime_worker_loop(self, generation: int) -> None:\n        \"\"\"热升级兜底：init_plugin 已执行但 MoviePilot 尚未重建公共服务时，自行维持检查链。\"\"\"\n        stop = getattr(self, "_runtime_stop", None)\n        if stop is None:\n            return\n        # 给插件管理器完成本轮装载，随后立即检查一次缓存。\n        if stop.wait(1.5):\n            return\n        if generation != type(self)._runtime_generation or not self._enabled:\n            return\n        try:\n            self._plugin_log("INFO", "【光鸭转存助手】【启动检查】内置守护开始首轮缓存检查")\n            self._startup_check()\n        except Exception as err:\n            self._plugin_log("EXCEPTION", "【光鸭转存助手】【启动检查】内置守护首轮执行异常：%s", err)\n\n        while self._enabled and generation == type(self)._runtime_generation:\n            interval = max(60, int(self._refresh_minutes or 5) * 60)\n            if stop.wait(interval):\n                return\n            if generation != type(self)._runtime_generation or not self._enabled:\n                return\n            heartbeat = float(getattr(self, "_host_tick_heartbeat", 0.0) or 0.0)\n            # 宿主公共服务在最近 1.5 个周期内正常执行时，内置守护只保活不重复跑。\n            if heartbeat and (time.monotonic() - heartbeat) < interval * 1.5:\n                continue\n            try:\n                self._plugin_log(\n                    "WARNING",\n                    "【光鸭转存助手】【服务回退】未检测到宿主定时服务心跳，内置守护执行本轮检查；无需手动保存配置",\n                )\n                self._tick(host_service=False)\n            except Exception as err:\n                self._plugin_log("EXCEPTION", "【光鸭转存助手】【服务回退】内置守护执行异常：%s", err)\n\n    def _startup_check(self) -> None:\n        \"\"\"启动后先消费本地索引，不等待首个 interval；随后再按游标做一次到期增量发现。\"\"\"\n'''
replace_once(anchor, insert, 'runtime worker insert')

replace_once(
'''    def _tick(self) -> None:\n        self._install_takeover()\n''',
'''    def _tick(self, host_service: bool = True) -> None:\n        if host_service:\n            self._host_tick_heartbeat = time.monotonic()\n            self._plugin_log("INFO", "【光鸭转存助手】【服务】宿主定时服务心跳已确认")\n        self._install_takeover()\n''',
'tick heartbeat')

replace_once(
'''    def stop_service(self) -> None:\n        self._restore_takeover()\n        self._inspect_cache.clear()\n''',
'''    def stop_service(self) -> None:\n        try:\n            stop = getattr(self, "_runtime_stop", None)\n            if stop is not None:\n                stop.set()\n            with type(self)._runtime_generation_lock:\n                type(self)._runtime_generation += 1\n            thread = getattr(self, "_runtime_thread", None)\n            if thread and thread.is_alive() and thread is not threading.current_thread():\n                thread.join(timeout=1.0)\n        except Exception:\n            pass\n        self._restore_takeover()\n        self._inspect_cache.clear()\n''',
'stop runtime worker')

SRC.write_text(text, encoding='utf-8')

# Update versions/description.
package = json.loads(PACKAGE.read_text(encoding='utf-8'))
package['GuangYaTransferAssistant']['version'] = '1.6.5'
package['GuangYaTransferAssistant']['description'] = '热升级即用：无需再次保存设置即可启动缓存检查与周期守护；宿主定时服务未重新注册时由内置守护自动接管，恢复后自动避免重复执行。'
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
plugin = json.loads(PLUGIN.read_text(encoding='utf-8'))
plugin['version'] = '1.6.5'
plugin['description'] = package['GuangYaTransferAssistant']['description']
PLUGIN.write_text(json.dumps(plugin, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# Add/update contract tests.
tests = TEST.read_text(encoding='utf-8')
tests = tests.replace("assert package['version'] == '1.6.4' and local['version'] == '1.6.4'", "assert package['version'] == '1.6.5' and local['version'] == '1.6.5'")
tests = tests.replace("assert 'plugin_version = \"1.6.4\"' in text", "assert 'plugin_version = \"1.6.5\"' in text")
tests = tests.replace("assert 'GuangYaTransferAssistantStartup' in service\n    assert '\"trigger\": \"date\"' in service\n    assert '_startup_check' in text", "assert 'GuangYaTransferAssistantTick' in service\n    assert '_startup_check' in text")
if 'def test_v165_hot_upgrade_runs_without_config_save()' not in tests:
    tests += '''\n\ndef test_v165_hot_upgrade_runs_without_config_save():\n    assert 'plugin_version = "1.6.5"' in text\n    init = text.split('    def init_plugin(', 1)[1].split('    def get_state(', 1)[0]\n    assert '_start_runtime_worker()' in init\n    assert '无需进入设置页再次保存' in text\n    assert '_runtime_worker_loop' in text\n    assert '【光鸭转存助手】【服务回退】' in text\n    assert '_tick(host_service=False)' in text\n    tick = text.split('    def _tick(', 1)[1].split('    def _process_selected_subscriptions(', 1)[0]\n    assert 'host_service: bool = True' in text\n    assert '_host_tick_heartbeat = time.monotonic()' in tick\n    stop = text.split('    def stop_service(', 1)[1]\n    assert '_runtime_stop' in stop and 'thread.join' in stop\n\n'''
TEST.write_text(tests, encoding='utf-8')
print('GuangYa v1.6.5 hot-upgrade runtime patch applied')
