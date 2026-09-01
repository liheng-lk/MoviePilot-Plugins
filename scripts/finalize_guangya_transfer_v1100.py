from pathlib import Path
import json
import textwrap

root = Path(__file__).resolve().parents[1]
plugin = root / "plugins.v3" / "guangyatransferassistant"
entry_path = plugin / "__init__.py"
entry = entry_path.read_text(encoding="utf-8")

entry = entry.replace('"""光鸭转存助手 v1.9.6 运行入口。', '"""光鸭转存助手 v1.10.0 运行入口。')
if "from .config_ui_v1100 import GuangYaConfigUiV1100Mixin" not in entry:
    entry = entry.replace(
        "from .config_ui_v192 import GuangYaConfigUiMixin\n",
        "from .config_ui_v1100 import GuangYaConfigUiV1100Mixin\n"
        "from .console_ui_v1100 import GuangYaConsoleUiV1100Mixin\n"
        "from .provider_reliability_v1100 import GuangYaProviderReliabilityV1100Mixin\n"
        "from .xunlei_reliability_v1100 import GuangYaXunleiReliabilityV1100Mixin\n"
        "from .config_ui_v192 import GuangYaConfigUiMixin\n",
    )
entry = entry.replace(
    "class GuangYaTransferAssistant(\n    GuangYaConfigUiMixin,",
    "class GuangYaTransferAssistant(\n"
    "    GuangYaConfigUiV1100Mixin,\n"
    "    GuangYaConsoleUiV1100Mixin,\n"
    "    GuangYaProviderReliabilityV1100Mixin,\n"
    "    GuangYaXunleiReliabilityV1100Mixin,\n"
    "    GuangYaConfigUiMixin,",
)
entry = entry.replace('    plugin_version = "1.9.6"', '    plugin_version = "1.10.0"')
entry = entry.replace('    build_id = "20260901-r10"', '    build_id = "20260901-r11"')
if "v1.10.0 重构首页/配置页" not in entry:
    marker = "v1.9.4 收口 IDN 节点身份、Cookie 域边界、搜索降级、迅雷 captcha/device、GCID 回退和配置/状态页信息层级；v1.9.5 迁移 PluginManager 到 MoviePilot V3 稳定 SDK。"
    entry = entry.replace(
        marker,
        marker + "\nv1.9.6 兼容 MoviePilot 最新订阅合同；v1.10.0 重构首页/配置页，并修复统一观影/磁力搜索与迅雷 Range 秒传边界。",
    )
entry_path.write_text(entry, encoding="utf-8")

package_path = root / "package.v3.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
item = package["GuangYaTransferAssistant"]
item["version"] = "1.10.0"
item["description"] = "固定分流与多来源订阅助手：新版控制台直接提供观影/迅雷/Magnet/ED2K 统一搜索和秒传预检；观影 GYING 支持节点发现、IDN 归一、自动切换、浏览器计算验证、真实登录/搜索/downurl；迅雷分享最高优先级走光鸭 userres 秒传，后续为光鸭直接转存 > Magnet > ED2K。"
history = dict(item.get("history") or {})
item["history"] = {
    "v1.10.0": "重构配置页与状态控制台为响应式卡片工作台，首页新增资源来源健康、统一搜索、秒传预检和最近命中表；修复观影手动搜索只返回 Magnet/ED2K 而看不到迅雷分享的问题；通用 Magnet/ED2K API 自动兼容 q/kw/keyword/search 与 Bearer/X-API-Key；迅雷 CID 改为严格 stream=True 的 3×20KiB 有界 Range 采样，服务器忽略中/尾 Range 时立即放弃，绝不整文件读取。",
    **history,
}
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

plugin_json_path = plugin / "plugin.json"
local = json.loads(plugin_json_path.read_text(encoding="utf-8"))
local["version"] = "1.10.0"
local["description"] = "MoviePilot V3 固定分流与多来源订阅助手：新版响应式控制台提供观影/迅雷/Magnet/ED2K 统一搜索、资源来源健康检测与秒传预检；固定优先级“观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K”。"
plugin_json_path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

readme_path = plugin / "README.md"
readme = readme_path.read_text(encoding="utf-8")
section = """
## v1.10.0：控制台、统一搜索与秒传可靠性

- 首页重构为响应式控制台：资源来源健康、固定优先级、搜索缺失资源、秒传预检、最近搜索结果和异常/在途任务同屏展示。
- 配置页按“接管与保存 / 资源来源 / 观影与迅雷秒传 / 高级设置”重排，协议细节默认折叠，不改变任何已有配置键。
- `/providers/search` 现在统一返回观影迅雷、Magnet 与 ED2K；`/providers/search/selected` 可直接搜索已选择的固定转存订阅。
- Magnet/ED2K API 自动兼容 `q` / `kw` / `keyword` / `search`，并修正 token 认证头。
- 新增 `/xunlei/flash/preflight`，非破坏性检查观影会话、迅雷 captcha/device/client 与光鸭 userres 运行时。
- 迅雷 CID 样本严格使用 `stream=True`，单段最多 20KiB；中/尾 Range 被服务器忽略时立即放弃，不下载整文件。

"""
if "## v1.10.0：控制台、统一搜索与秒传可靠性" not in readme:
    first_break = readme.find("\n")
    readme = readme[: first_break + 1] + section + readme[first_break + 1 :]
readme_path.write_text(readme, encoding="utf-8")

tests_dir = root / "tests" / "v3" / "guangyatransferassistant"
for test in tests_dir.glob("test_*.py"):
    text = test.read_text(encoding="utf-8")
    text = text.replace('== "1.9.6"', '== "1.10.0"')
    text = text.replace("== '1.9.6'", "== '1.10.0'")
    text = text.replace("'plugin_version = \"1.9.6\"'", "'plugin_version = \"1.10.0\"'")
    text = text.replace("'build_id = \"20260901-r10\"'", "'build_id = \"20260901-r11\"'")
    test.write_text(text, encoding="utf-8")

v1100_test = tests_dir / "test_v1100_ui_runtime.py"
v1100_test.write_text(textwrap.dedent(r'''
    import ast
    import json
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[3]
    PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
    ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    PROVIDER = (PLUGIN / "provider_reliability_v1100.py").read_text(encoding="utf-8")
    XUNLEI = (PLUGIN / "xunlei_reliability_v1100.py").read_text(encoding="utf-8")
    CONSOLE = (PLUGIN / "console_ui_v1100.py").read_text(encoding="utf-8")
    CONFIG = (PLUGIN / "config_ui_v1100.py").read_text(encoding="utf-8")

    def test_v1100_files_parse_and_publish_current_release():
        for path in (PLUGIN / "provider_reliability_v1100.py", PLUGIN / "xunlei_reliability_v1100.py", PLUGIN / "console_ui_v1100.py", PLUGIN / "config_ui_v1100.py", PLUGIN / "__init__.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
        local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        assert package["version"] == local["version"] == "1.10.0"
        assert 'plugin_version = "1.10.0"' in ENTRY
        assert 'build_id = "20260901-r11"' in ENTRY

    def test_v1100_mro_installs_final_layers_before_old_layers():
        start = ENTRY.index("class GuangYaTransferAssistant")
        for token in ("GuangYaConfigUiV1100Mixin,", "GuangYaConsoleUiV1100Mixin,", "GuangYaProviderReliabilityV1100Mixin,", "GuangYaXunleiReliabilityV1100Mixin,"):
            assert token in ENTRY[start:]
        assert ENTRY.index("GuangYaConfigUiV1100Mixin,", start) < ENTRY.index("GuangYaConfigUiMixin,", start)
        assert ENTRY.index("GuangYaConsoleUiV1100Mixin,", start) < ENTRY.index("GuangYaStatusHardeningMixin,", start)
        assert ENTRY.index("GuangYaProviderReliabilityV1100Mixin,", start) < ENTRY.index("GuangYaProviderSourcesMixin,", start)
        assert ENTRY.index("GuangYaXunleiReliabilityV1100Mixin,", start) < ENTRY.index("GuangYaXunleiFlashMixin,", start)

    def test_unified_search_exposes_xunlei_and_adaptive_magnet_queries():
        for token in ('"q"', '"kw"', '"keyword"', '"search"', "_search_viewing_xunlei", '"xunlei"', '"/providers/search/selected"'):
            assert token in PROVIDER
        assert 'headers["Authorization"] = f"Bearer {raw}"' in PROVIDER
        assert 'headers["X-API-Key"] = raw' in PROVIDER
        assert "api_provider_test" in PROVIDER and "_search_api_provider(item, keyword)" in PROVIDER

    def test_xunlei_sampling_is_streamed_and_bounded():
        assert "stream=True" in XUNLEI
        assert "iter_content" in XUNLEI
        assert "_CID_SAMPLE_SIZE = 20 * 1024" in XUNLEI
        assert "if start != 0:" in XUNLEI
        assert "response.close()" in XUNLEI
        assert "response.content" not in XUNLEI
        assert '"/xunlei/flash/preflight"' in XUNLEI
        assert "_get_guangya_runtime" in XUNLEI

    def test_console_is_responsive_and_has_real_actions():
        for token in ("border-radius:18px", '"sm": 6', '"md": 3', "VDataTable", "搜索缺失资源", "秒传预检", "检测资源来源", "刷新观影节点"):
            assert token in CONSOLE
        for endpoint in ("/providers/search/selected", "/providers/test", "/xunlei/flash/preflight", "/viewing/nodes/refresh"):
            assert endpoint in CONSOLE
        priority = ["① 迅雷秒传", "② 光鸭直存", "③ Magnet", "④ ED2K"]
        positions = [CONSOLE.index(value) for value in priority]
        assert positions == sorted(positions)

    def test_config_ui_keeps_models_and_folds_protocol_details():
        for token in ("VExpansionPanels", "接管与保存", "资源来源", "观影与迅雷秒传", "高级设置", "xunlei_captcha_init_json", "viewing_registry_urls"):
            assert token in CONFIG
        for model in ("selected_subscriptions", "save_path", "channel_urls", "magnet_api_sources", "viewing_username", "viewing_password", "xunlei_flash_enabled"):
            assert model in CONFIG
''').lstrip(), encoding="utf-8")
