from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"

# Runtime entry: bind the legacy/routing PluginAction handler on the real final plugin class.
entry_path = PLUGIN / "__init__.py"
entry = entry_path.read_text(encoding="utf-8")
entry = entry.replace('"""光鸭转存助手 v1.12.7 运行入口。', '"""光鸭转存助手 v1.12.8 运行入口。', 1)
if "v1.12.8 修复 /gysub 消息入口" not in entry:
    entry = entry.replace(
        "v1.12.7 修复“已找到资源/缺集但未提交光鸭”：S02+ 季发行年份不再被系列首播年份误杀；GYING 已命中且真实分享顶层名/文件结构一致时允许合法别名桥接；拆包 needs_review 在证据变化或 6 小时后自动重评，并补齐拆包决策日志。\n",
        "v1.12.7 修复“已找到资源/缺集但未提交光鸭”：S02+ 季发行年份不再被系列首播年份误杀；GYING 已命中且真实分享顶层名/文件结构一致时允许合法别名桥接；拆包 needs_review 在证据变化或 6 小时后自动重评，并补齐拆包决策日志。\n"
        "v1.12.8 修复 /gysub 消息入口：最终插件类显式注册 routing PluginAction 桥，不再依赖继承层隐式事件绑定；合法直订请求先即时回执，再执行 TMDB 识别和订阅创建，避免上游变慢时消息端表现为无响应。\n",
        1,
    )
bridge = '''    @eventmanager.register(EventType.PluginAction)\n    def action_event_handler(self, event: Event) -> None:\n        \"\"\"把 routing 层的 /gysub 等 PluginAction 显式绑定到最终插件类。\"\"\"\n        event_data = event.event_data or {}\n        action = str(event_data.get(\"action\") or \"\")\n        try:\n            return super().action_event_handler(event)\n        except Exception as err:\n            self._plugin_log(\"EXCEPTION\", \"【光鸭转存助手】【消息命令v1.12.8】action=%s 处理异常：%s\", action, err)\n            if action in {\"guangya_direct_subscribe\", \"guangya_route_status\", \"guangya_release_native\"}:\n                self._post_command(event_data, \"光鸭命令处理失败\", str(err)[:500])\n            return None\n\n'''
anchor = '    @eventmanager.register(EventType.PluginAction)\n    def experience_action_event_handler(self, event: Event) -> None:\n'
if bridge not in entry:
    assert anchor in entry, "final PluginAction experience bridge anchor missing"
    entry = entry.replace(anchor, bridge + anchor, 1)
entry = entry.replace('plugin_version = "1.12.7"', 'plugin_version = "1.12.8"', 1)
entry = entry.replace('build_id = "20260905-r53"', 'build_id = "20260905-r54"', 1)
entry_path.write_text(entry, encoding="utf-8")

# Routing: acknowledge a valid /gysub before any TMDB network lookup.
routing_path = PLUGIN / "routing_v170.py"
routing = routing_path.read_text(encoding="utf-8")
old = '''        try:\n            candidates = self._search_direct_candidates(request)\n'''
new = '''        self._plugin_log(\n            "INFO",\n            "【光鸭转存助手】【消息命令v1.12.8】已收到 /gysub 请求，开始识别媒体",\n        )\n        self._post_command(\n            event_data,\n            "⏳ 已收到光鸭直订请求",\n            "正在识别媒体并创建订阅；识别完成后会继续回传结果。",\n        )\n        try:\n            candidates = self._search_direct_candidates(request)\n'''
if new not in routing:
    assert old in routing, "gysub search anchor missing"
    routing = routing.replace(old, new, 1)
routing_path.write_text(routing, encoding="utf-8")

# Public metadata.
description = (
    "更新日历驱动的固定分流助手：5 分钟频道 Push 被动消费；当天应播 TV/动漫每 10 分钟快速追更；"
    "v1.12.8 修复 /gysub 消息无响应回归，最终插件类显式接管 routing PluginAction，并在 TMDB 识别前立即回执；"
    "保留 v1.12.7 的 S02+ 季发行年份、合法别名和拆包 needs_review 恢复修复；"
    "来源优先级仍为观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；非更新日不主动访问外部资源站，04:10 每日全员复核兜底。"
)
history_text = (
    "修复升级后 /gysub 等 routing 消息命令可能完全无反馈的问题：在最终 GuangYaTransferAssistant 类上显式注册 action_event_handler，"
    "通过当前 runtime-owner 可靠性层继续落到 routing handler，不再依赖 mixin 继承层的隐式事件绑定；合法 /gysub 请求在调用 TMDB 媒体搜索前先立即回执，"
    "即使上游识别变慢也不会表现为消息黑洞。资源门禁、拆包和来源优先级不变。"
)
plugin_json_path = PLUGIN / "plugin.json"
plugin_json = json.loads(plugin_json_path.read_text(encoding="utf-8"))
plugin_json["version"] = "1.12.8"
plugin_json["description"] = description
plugin_json_path.write_text(json.dumps(plugin_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

package_path = ROOT / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
row = package["GuangYaTransferAssistant"]
row["version"] = "1.12.8"
row["description"] = description
history = dict(row.get("history") or {})
row["history"] = {"v1.12.8": history_text, **history}
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

readme_path = PLUGIN / "README.md"
readme = readme_path.read_text(encoding="utf-8")
note = '''\n## v1.12.8：/gysub 消息入口 hotfix\n\n- 最终插件类显式注册 routing `PluginAction` 桥，`/gysub`、`/gystatus`、`/gynative` 不再依赖隐式继承事件绑定。\n- `/gysub` 参数合法后立即回复“已收到光鸭直订请求”，再执行 TMDB 识别和订阅创建；上游变慢时也不会再无反馈。\n- 事件处理异常会记录 `【消息命令v1.12.8】` 并尽量向原消息通道回传失败信息。\n- 不改 v1.12.7 的资源门禁、拆包、迅雷 JSON 或来源优先级。\n'''
if "## v1.12.8：/gysub 消息入口 hotfix" not in readme:
    pos = readme.find("\n## ")
    readme = (readme[:pos] + note + readme[pos:]) if pos >= 0 else (readme + note)
readme_path.write_text(readme, encoding="utf-8")

# Current-release test expectations. Preserve the historical v1.12.7 resource-gate module marker.
for path in (ROOT / "tests").rglob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    original = text
    text = text.replace('"1.12.7"', '"1.12.8"')
    text = text.replace("'1.12.7'", "'1.12.8'")
    text = text.replace('plugin_version = "1.12.7"', 'plugin_version = "1.12.8"')
    text = text.replace('build_id = "20260905-r53"', 'build_id = "20260905-r54"')
    if path.name == "test_resource_gate_v1127.py":
        text = text.replace("assert 'plugin_version = \"1.12.8\"' in gate_text", "assert 'plugin_version = \"1.12.7\"' in gate_text")
        text = text.replace("assert 'build_id = \"20260905-r54\"' in gate_text", "assert 'build_id = \"20260905-r53\"' in gate_text")
        text = text.replace('assert "v1.12.8" in package["history"]\n    assert "v1.12.6" in package["history"]', 'assert "v1.12.8" in package["history"]\n    assert "v1.12.7" in package["history"]\n    assert "v1.12.6" in package["history"]')
    if text != original:
        path.write_text(text, encoding="utf-8")

# Dedicated regression contract.
bridge_test = ROOT / "tests/v3/guangyatransferassistant/test_command_bridge_v1128.py"
bridge_test.write_text('''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[3]\nPLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"\nENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")\nROUTING = (PLUGIN / "routing_v170.py").read_text(encoding="utf-8")\n\n\ndef test_final_runtime_explicitly_binds_routing_plugin_action_handler():\n    class_body = ENTRY.split("class GuangYaTransferAssistant(", 1)[1]\n    assert "def action_event_handler(self, event: Event) -> None:" in class_body\n    assert "return super().action_event_handler(event)" in class_body\n    assert class_body.count("@eventmanager.register(EventType.PluginAction)") >= 2\n\n\ndef test_gysub_still_routes_to_direct_subscribe_handler():\n    assert 'if action == "guangya_direct_subscribe":' in ROUTING\n    assert "self._handle_direct_subscribe_command(event_data)" in ROUTING\n\n\ndef test_gysub_ack_is_sent_before_tmdb_lookup():\n    handler = ROUTING.split("def _handle_direct_subscribe_command", 1)[1].split("def _spawn_command_transfer", 1)[0]\n    ack = handler.index("⏳ 已收到光鸭直订请求")\n    lookup = handler.index("self._search_direct_candidates(request)")\n    assert ack < lookup\n    assert "识别完成后会继续回传结果" in handler\n\n\ndef test_v1128_metadata_and_previous_resource_gate_remain_active():\n    assert 'plugin_version = "1.12.8"' in ENTRY\n    assert 'build_id = "20260905-r54"' in ENTRY\n    assert "GuangYaResourceGateV1127Mixin" in ENTRY\n''', encoding="utf-8")

Path(__file__).unlink()
