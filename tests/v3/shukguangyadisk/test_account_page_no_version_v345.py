from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PAGE = (ROOT / "plugins.v3" / "shukguangyadisk" / "dist" / "assets" / "__federation_expose_AssistantPage-dev.js").read_text(encoding="utf-8")


def test_account_page_has_no_internal_version_badge():
    assert "gy-version" not in PAGE
    assert "v2.2.15" not in PAGE
    assert "光鸭云盘助手" in PAGE
