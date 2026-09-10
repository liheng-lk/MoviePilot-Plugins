from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"


def test_final_v11217_tree_is_publishable_and_temp_tooling_is_removed():
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    recall = (PLUGIN / "search_recall_v11217.py").read_text(encoding="utf-8")
    bilingual = (PLUGIN / "movie_bilingual_identity_v11216.py").read_text(encoding="utf-8")

    assert 'plugin_version = "2.0.7"' in entry
    assert 'build_id = "20260910-r88"' in entry
    assert plugin["version"] == "2.0.7"
    assert package["GuangYaTransferAssistant"]["version"] == "2.0.7"
    assert 'class GuangYaSearchRecallV11217Mixin' in recall
    assert 'class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):' in bilingual
    assert 'plugin_version = "1.12.16"' in bilingual
    assert 'build_id = "20260906-r63"' in bilingual
    assert not (ROOT / "scripts/_prepare_guangya_v11217.py").exists()
    assert not (ROOT / ".github/workflows/prepare-guangya-v11217.yml").exists()

