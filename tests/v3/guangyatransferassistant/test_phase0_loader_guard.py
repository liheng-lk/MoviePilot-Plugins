"""Phase 0：Loader 护栏合同（不改业务版本号）。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ENTRY = (ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py").read_text(
    encoding="utf-8"
)


def test_phase0_loader_scrub_helpers_exist_without_version_bump():
    assert 'plugin_version = "2.0.13"' in ENTRY
    assert "def _scrub_public_mixin_exports()" in ENTRY
    assert "def _emergency_restore_subscribe_chain_patches()" in ENTRY
    assert "_scrub_public_mixin_exports()" in ENTRY
    assert "_emergency_restore_subscribe_chain_patches()" in ENTRY
    # Phase 0 禁止接入 V2 运行入口
    assert "gy2_plugin" not in ENTRY
    assert "_GuangYaTransferV2Mixin" not in ENTRY


def test_phase0_public_export_contract_in_source():
    assert '__all__ = ["GuangYaTransferAssistant"]' in ENTRY
    # 仍通过 MRO 组合能力，但模块末尾会 scrub Mixin 名
    head = ENTRY.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
    assert "GuangYaPagePerfV1123Mixin" in head
    assert "GuangYaExperienceMixin" in head
