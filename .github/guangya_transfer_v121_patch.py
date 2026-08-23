from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
TEST = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_plugin_contract.py"
PACKAGE = ROOT / "package.v3.json"
LOCAL = ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json"

text = SRC.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one occurrence, got {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)


# 1) 路径值归一化：兼容 VCombobox 返回对象，以及 1.2.0 已保存的 dict 字符串。
marker = "\ndef _file_extension(value: Any) -> str:\n"
helper = r'''

def _normalize_config_path(value: Any, default: str = "/光鸭转存") -> str:
    """把 VCombobox 的字符串/对象/旧对象字符串统一成绝对云盘路径。"""
    candidate = value
    if isinstance(candidate, dict):
        candidate = candidate.get("value") or candidate.get("title") or default
    elif isinstance(candidate, (list, tuple)) and candidate:
        candidate = candidate[0]
        if isinstance(candidate, dict):
            candidate = candidate.get("value") or candidate.get("title") or default

    raw = str(candidate if candidate not in (None, "") else default).strip()
    # 兼容 1.2.0 错误持久化的：{'title': '/光鸭媒体库', 'value': '/光鸭媒体库'}
    if raw.startswith("{") and ("value" in raw or "title" in raw):
        matched = re.search(r'''["'](?:value|title)["']\s*:\s*["']([^"']+)["']''', raw)
        if matched:
            raw = matched.group(1).strip()
    normalized = _safe_relative_path(raw)
    return f"/{normalized}" if normalized else "/"
'''
if marker not in text:
    raise RuntimeError("file extension marker missing")
text = text.replace(marker, helper + marker, 1)

# 2) 版本与产品语义改为“固定分流”，彻底取消优先/失败回退。
replace_once(
    'class GuangYaTransferAssistant(_PluginBase):\n    """对用户勾选的订阅优先尝试光鸭频道转存，未勾选保持 MoviePilot 原生路线。"""',
    'class GuangYaTransferAssistant(_PluginBase):\n    """对用户勾选的订阅固定走光鸭转存，未勾选固定走 MoviePilot 原生下载。"""',
)
replace_once(
    '    plugin_desc = "读取指定 Telegram 光鸭资源频道，对手动勾选的 MoviePilot 订阅优先匹配并转存光鸭分享；未勾选或转存失败时继续原生订阅下载。"',
    '    plugin_desc = "订阅固定分流：手动勾选的订阅只使用光鸭频道转存，未勾选订阅只使用 MoviePilot 原生下载。"',
)
replace_once('    plugin_version = "1.2.0"', '    plugin_version = "1.2.1"')
replace_once('    plugin_label = "光鸭云盘,转存,订阅,Telegram,网盘,下载回退"', '    plugin_label = "光鸭云盘,转存,订阅,Telegram,网盘,固定分流"')
replace_once('    _fallback_native = True\n', '')

# 3) 配置读取时立即修复错误 save_path，并自动写回干净字符串。
replace_once(
    '        self._save_path = str(config.get("save_path") or "/光鸭转存").strip() or "/"\n        self._create_media_folder = bool(config.get("create_media_folder", False))\n        self._fallback_native = bool(config.get("fallback_native", True))',
    '        raw_save_path = config.get("save_path")\n        self._save_path = _normalize_config_path(raw_save_path, "/光鸭转存")\n        path_migrated = raw_save_path not in (None, "") and raw_save_path != self._save_path\n        self._create_media_folder = bool(config.get("create_media_folder", False))',
)
replace_once(
    '        self._cleanup_selected_ids()\n        if self._enabled:',
    '        self._cleanup_selected_ids()\n        if path_migrated:\n            logger.info("【光鸭转存助手】【路径】目标目录配置已规范化：%s -> %s", raw_save_path, self._save_path)\n            self._save_config()\n        if self._enabled:',
)

# 4) UI：删除“失败回退”开关，明确勾选=转存专用，未勾选=原生专用。
replace_once(
    '{"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用转存优先路由"}}]},',
    '{"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用订阅固定分流"}}]},',
)
replace_once(
    '                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "fallback_native", "label": "未命中/失败回退原生下载"}}]},\n',
    '',
)
replace_once(
    '{"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "转存结果通知"}}]},',
    '{"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "转存结果通知"}}]},',
)
replace_once(
    '{"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "proxy", "label": "频道读取使用代理"}}]},',
    '{"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "proxy", "label": "频道读取使用代理"}}]},',
)
replace_once('"label": "选择走光鸭优先的订阅"', '"label": "选择仅使用光鸭转存的订阅"')
replace_once(
    '                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "支持明文链接、查看资源隐藏按钮、URL编码/包装链接。仅接管手动勾选且状态为新建/订阅中的项目；暂停/待定、洗版订阅、严格模式下的复杂规则订阅继续走 MoviePilot 原路线。电视剧会跳过 note 已记录剧集，确认转存后再同步订阅进度。"}},',
    '                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "固定分流模式：已勾选订阅只走光鸭转存，即使暂时无资源或转存失败也不会启动原生下载；未勾选订阅完全走 MoviePilot 原生下载。暂停/待定不会执行转存；洗版或复杂规则如需原生处理，请取消勾选。"}},',
)
replace_once('            "fallback_native": self._fallback_native,\n', '')
replace_once('            "fallback_native": self._fallback_native,\n', '')

# 5) 固定分流核心：选中后永远不调用 SubscribeChain.search。
start = text.index('    def _dispatch_subscribe_search(')
end = text.index('    def _subscription_static_guard(', start)
new_dispatch = '''    def _dispatch_subscribe_search(self, sid: Optional[int] = None, state: Optional[str] = "R", manual: Optional[bool] = False, progress_callback=None):
        """固定分流：已勾选只转存，未勾选只走 MoviePilot 原生下载。"""
        with self._route_lock:
            selected = set(self._selected_subscriptions)
            if sid:
                if int(sid) not in selected:
                    return SubscribeChain().search(sid=sid, state=state, manual=manual, progress_callback=progress_callback)
                subscribe = self._find_subscription(int(sid))
                if not subscribe:
                    logger.warning("【光鸭转存助手】【分流】已勾选订阅 #%s 不存在；固定转存路线不触发原生下载", sid)
                    return True
                result = self._try_transfer_subscription(subscribe)
                logger.info("【光鸭转存助手】【分流】#%s %s 固定转存处理：%s", sid, getattr(subscribe, "name", ""), result.get("message") or "完成")
                return True

            subscriptions = self._list_subscriptions(state or "N,R")
            for index, subscribe in enumerate(subscriptions):
                subscribe_id = int(getattr(subscribe, "id", 0) or 0)
                if not subscribe_id:
                    continue
                callback = progress_callback if index == 0 else None
                if subscribe_id in selected:
                    result = self._try_transfer_subscription(subscribe)
                    logger.info("【光鸭转存助手】【分流】#%s %s 固定转存处理：%s", subscribe_id, getattr(subscribe, "name", ""), result.get("message") or "完成")
                    continue
                SubscribeChain().search(sid=subscribe_id, state=None, manual=manual, progress_callback=callback)
            return True

'''
text = text[:start] + new_dispatch + text[end:]

# 6) 对已选订阅，所有“暂时不可转/失败/部分成功”都视为转存路线已接管，不允许原生下载。
replace_once('            return {"success": False, "handled": False, "message": guard_reason}', '            return {"success": False, "handled": True, "message": guard_reason}')
replace_once(
    '            detail = "仅命中旧缓存，不能阻断原生下载" if stale_matches else "频道未匹配到光鸭分享"\n            logger.info("【光鸭转存助手】【匹配】#%s %s %s；%s", sid, getattr(subscribe, "name", ""), detail, "将由 MoviePilot 原订阅任务继续下载" if self._fallback_native else "原生下载回退已关闭")\n            return {"success": False, "handled": False, "message": detail}',
    '            detail = "仅命中旧缓存，等待频道恢复" if stale_matches else "频道暂未匹配到光鸭分享"\n            logger.info("【光鸭转存助手】【匹配】#%s %s %s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), detail)\n            return {"success": False, "handled": True, "message": detail}',
)
replace_once('"状态：部分转存完成，剩余将回原订阅处理" if partial else "状态：增量转存已确认完成",', '"状态：部分转存完成，剩余保持转存路线等待下轮" if partial else "状态：增量转存已确认完成",')
replace_once(
    '                return {"success": False, "handled": False, "message": f"部分转存 {len(unique_paths)} 个文件，剩余回退原订阅", "new_count": len(unique_paths), "target_path": target_path}',
    '                return {"success": False, "handled": True, "message": f"部分转存 {len(unique_paths)} 个文件，剩余等待下轮转存", "new_count": len(unique_paths), "target_path": target_path}',
)
replace_once(
    '        logger.warning("【光鸭转存助手】【回退】#%s %s 转存未完成：%s；%s", sid, getattr(subscribe, "name", ""), final_message, "将回退 MoviePilot 原生下载" if self._fallback_native else "原生下载回退已关闭")',
    '        logger.warning("【光鸭转存助手】【失败】#%s %s 转存未完成：%s；固定转存路线不触发原生下载", sid, getattr(subscribe, "name", ""), final_message)',
)
replace_once(
    '+ ("后续：将回退 MoviePilot 原生下载" if self._fallback_native else "后续：原生下载回退已关闭")',
    '+ "后续：保持转存路线，等待频道刷新或下次重试"',
)
replace_once('        return {"success": False, "handled": False, "message": final_message}', '        return {"success": False, "handled": True, "message": final_message}')

# 规则提示不再暗示自动回退。
text = text.replace('"洗版订阅保留 MoviePilot 原生质量优先级逻辑"', '"洗版订阅不支持固定转存；如需原生处理请取消勾选"')
text = text.replace('"存在复杂过滤规则组，严格模式下交回原生下载"', '"存在复杂过滤规则组；如需原生处理请取消勾选"')
text = text.replace('"存在复杂过滤规则，严格模式下交回原生下载"', '"存在复杂过滤规则；如需原生处理请取消勾选"')

# 7) 目标路径修复：配置、目标路径、真正 restore 前三层都归一化。
replace_once(
    '    def _target_path(self, subscribe: Any) -> str:\n        base = "/" + _safe_relative_path(self._save_path) if _safe_relative_path(self._save_path) else "/"',
    '    def _target_path(self, subscribe: Any) -> str:\n        base = _normalize_config_path(self._save_path, "/")',
)
replace_once(
    '    def _restore_items(self, probe: Dict[str, Any], save_path: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:\n        client, api = self._get_guangya_runtime()',
    '    def _restore_items(self, probe: Dict[str, Any], save_path: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:\n        save_path = _normalize_config_path(save_path, "/")\n        client, api = self._get_guangya_runtime()',
)
replace_once(
    '                base = "/" + str(save_path or "/").strip("/") if str(save_path or "/").strip("/") else "/"',
    '                base = _normalize_config_path(save_path, "/")',
)
replace_once('                    result.append(row if raw else {"title": row["title"], "value": row["value"]})', '                    result.append(row if raw else row["value"])')

if '_fallback_native' in text or '"fallback_native"' in text:
    raise RuntimeError("fallback_native still present after fixed-routing patch")

SRC.write_text(text, encoding="utf-8")

# 8) 元数据版本。
package = json.loads(PACKAGE.read_text(encoding="utf-8"))
entry = package["GuangYaTransferAssistant"]
entry["description"] = "光鸭订阅固定分流：勾选订阅只转存、未勾选只原生下载；修复目标目录对象值导致的转存失败，并保留隐藏链接、TMDB精确匹配和文件级增量去重。"
entry["version"] = "1.2.1"
history = entry.setdefault("history", {})
history = {"v1.2.1": "改为确定性固定分流：勾选订阅只使用光鸭转存，无资源或失败也不触发原生下载；未勾选订阅完全使用 MoviePilot 原生下载。修复 VCombobox 将目标目录保存为 title/value 对象导致路径被拼成字典字符串、无法创建目录的问题，并自动迁移旧错误配置。", **history}
entry["history"] = history
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

local = json.loads(LOCAL.read_text(encoding="utf-8"))
local["description"] = "订阅固定分流：勾选订阅只走光鸭转存，未勾选订阅只走 MoviePilot 原生下载；自动修复目标目录对象配置。"
local["version"] = "1.2.1"
LOCAL.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# 9) 回归测试版本与新增语义。
test = TEST.read_text(encoding="utf-8")
test = test.replace('package["version"] == "1.2.0" and local["version"] == "1.2.0"', 'package["version"] == "1.2.1" and local["version"] == "1.2.1"')
test = test.replace('assert \'plugin_version = "1.2.0"\' in text', 'assert \'plugin_version = "1.2.1"\' in text')
append = r'''


def test_fixed_routing_never_falls_back_for_selected_subscriptions():
    assert "_fallback_native" not in text
    assert '"fallback_native"' not in text
    dispatch = text.split("    def _dispatch_subscribe_search(", 1)[1].split("    def _subscription_static_guard(", 1)[0]
    assert dispatch.count("SubscribeChain().search") == 2
    assert "if int(sid) not in selected:" in dispatch
    assert "if subscribe_id in selected:" in dispatch
    assert "固定转存处理" in dispatch
    assert "continue" in dispatch
    assert "固定转存路线不触发原生下载" in text


def test_save_path_combobox_values_are_normalized():
    normalize = ns["_normalize_config_path"]
    assert normalize("/光鸭媒体库") == "/光鸭媒体库"
    assert normalize({"title": "/光鸭媒体库", "value": "/光鸭媒体库"}) == "/光鸭媒体库"
    assert normalize("{'title': '/光鸭媒体库', 'value': '/光鸭媒体库'}") == "/光鸭媒体库"
    assert normalize('{"title": "/光鸭媒体库", "value": "/光鸭媒体库"}') == "/光鸭媒体库"
    assert 'result.append(row if raw else row["value"])' in text
'''
if "test_fixed_routing_never_falls_back_for_selected_subscriptions" not in test:
    test += append
TEST.write_text(test, encoding="utf-8")

print("patched GuangYaTransferAssistant v1.2.1 fixed routing + path normalization")
