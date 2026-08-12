"""光鸭云盘助手 v1.1.2 回收站稳定性回归测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v2" / "shukguangyadisk"


def test_recycle_adapter_distinguishes_query_failure_from_missing_target():
    source = (PLUGIN / "guangya_api_v112.py").read_text(encoding="utf-8")
    assert "return results, False" in source
    assert "if last_query_ok:" in source
    assert "回收站查询正常且目标已不存在，按已彻底清理处理" in source
    assert "回收站查询连续失败，无法确认彻底删除状态" in source


def test_recycle_adapter_prefers_fileid_before_name_fallback():
    source = (PLUGIN / "guangya_api_v112.py").read_text(encoding="utf-8")
    fileid_pos = source.index("if target_fileid:")
    same_name_pos = source.index("same_name_items =")
    assert fileid_pos < same_name_pos


def test_recycle_adapter_keeps_task_missing_idempotent():
    source = (PLUGIN / "guangya_api_v112.py").read_text(encoding="utf-8")
    assert "self._is_task_missing(response)" in source
    assert "response.get(\"code\") in (142, 145, 147)" in source
    assert "allow_missing=True" in source


def test_runtime_uses_stability_adapter_and_version_is_v112():
    source = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert "from .guangya_api_v112 import GuangYaApi as _StableGuangYaApi" in source
    assert "_legacy_module.GuangYaApi = _StableGuangYaApi" in source
    assert 'plugin_version = "1.1.2"' in source


def test_v112_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
    root_meta = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))

    assert plugin_meta["version"] == "1.1.2"
    assert package_meta["ShukGuangYaDisk"]["version"] == "1.1.2"
    assert root_meta["ShukGuangYaDisk"]["version"] == "1.1.2"
    assert "v1.1.2" in plugin_meta["history"]
    assert "v1.1.2" in package_meta["ShukGuangYaDisk"]["history"]
    assert "v1.1.2" in root_meta["ShukGuangYaDisk"]["history"]
