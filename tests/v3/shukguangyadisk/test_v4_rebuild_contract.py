"""光鸭云盘助手 V4 重构合同测试。

这组测试故意先于实现提交：当前 3.9.x bundle 运行时必须失败，直到新的直接源码
`__init__.py` 替换旧架构。测试只锁定架构与公开契约，不依赖光鸭网络。
"""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_INIT = REPO_ROOT / "plugins.v3" / "shukguangyadisk" / "__init__.py"


class V4SingleFileArchitectureTest(unittest.TestCase):
    """验证 V4 是直接源码单文件，而不是历史虚拟模块容器。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PLUGIN_INIT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(PLUGIN_INIT))

    def test_bundle_loader_is_removed(self) -> None:
        """最终源码不得继续携带 JSON bundle 或自定义 import loader。"""
        forbidden = (
            "_BUNDLED_SOURCES",
            "MetaPathFinder",
            "SourceLoader",
            "_BundleFinder",
            "_BundleLoader",
            "<single-init:",
        )
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.source)

    def test_runtime_has_no_versioned_patch_installers(self) -> None:
        """V4 不允许 install_xxx_vNNN 形式的历史补丁安装器。"""
        offenders: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name.startswith("install_") and any(ch.isdigit() for ch in name):
                    offenders.append(name)
        self.assertEqual([], sorted(offenders))

    def test_required_v4_runtime_types_exist(self) -> None:
        """核心职责必须直接定义在同一个运行时文件中。"""
        classes = {
            node.name
            for node in self.tree.body
            if isinstance(node, ast.ClassDef)
        }
        required = {
            "GuangYaClient",
            "GuangYaApi",
            "ResourceStore",
            "StabilityDetector",
            "MoviePilotContextBuilder",
            "OrganizerExecutor",
            "OrganizerCoordinator",
            "MonitorService",
            "ShukGuangYaDisk",
        }
        self.assertEqual(set(), required - classes)

    def test_new_runtime_uses_moviepilot_v3_sdk_facades(self) -> None:
        """基础宿主能力优先从 MoviePilot V3 SDK 稳定门面导入。"""
        imports: set[tuple[str, str]] = set()
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                imports.add((node.module, alias.name))

        required = {
            ("app.sdk.logging", "logger"),
            ("app.sdk.events", "Event"),
            ("app.sdk.events", "eventmanager"),
            ("app.sdk.services", "StorageHelper"),
        }
        self.assertEqual(set(), required - imports)

    def test_runtime_does_not_regress_to_removed_legacy_module_paths(self) -> None:
        """V4 新代码不能把 V3 正式接口反向替换成旧物理路径。"""
        forbidden_modules = {
            "app.log",
            "app.core.event",
            "app.core.config",
            "app.helper.storage",
        }
        imported_modules = {
            node.module
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertEqual(set(), forbidden_modules & imported_modules)


@unittest.skipUnless(
    os.environ.get("MOVIEPILOT_SOURCE"),
    "设置 MOVIEPILOT_SOURCE 后执行真实 MoviePilot V3 import smoke",
)
class V4MoviePilotImportSmokeTest(unittest.TestCase):
    """在真实 MoviePilot V3 源码环境加载最终插件。"""

    def test_imports_against_real_moviepilot_v3(self) -> None:
        """插件必须在宿主真实模块树下完成 import 与实例化。"""
        mp_source = Path(os.environ["MOVIEPILOT_SOURCE"]).resolve()
        self.assertTrue((mp_source / "app").is_dir(), mp_source)
        sys.path.insert(0, str(mp_source))
        try:
            module_name = "shukguangyadisk_v4_contract"
            spec = importlib.util.spec_from_file_location(
                module_name,
                PLUGIN_INIT,
                submodule_search_locations=[str(PLUGIN_INIT.parent)],
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            plugin_cls = getattr(module, "ShukGuangYaDisk")
            plugin = plugin_cls()
            self.assertTrue(callable(getattr(plugin, "init_plugin")))
            self.assertTrue(callable(getattr(plugin, "get_api")))
        finally:
            sys.path = [item for item in sys.path if item != str(mp_source)]


if __name__ == "__main__":
    unittest.main(verbosity=2)
