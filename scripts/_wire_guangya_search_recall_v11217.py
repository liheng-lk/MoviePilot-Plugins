from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
TESTS = ROOT / "tests" / "v3" / "guangyatransferassistant"


def replace(path: Path, old: str, new: str, *, required: bool = True) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if required:
            raise RuntimeError(f"missing anchor in {path}: {old}")
        return
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    bilingual = PLUGIN / "movie_bilingual_identity_v11216.py"
    replace(
        bilingual,
        "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin",
        "from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin",
    )
    replace(
        bilingual,
        "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaManualCheckV11211Mixin):",
        "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):",
    )

    # 只迁移写死旧 nested chain 的结构合同；业务断言保持原样。
    old_class = "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaManualCheckV11211Mixin):"
    new_class = "class GuangYaMovieBilingualIdentityV11216Mixin(GuangYaSearchRecallV11217Mixin):"
    old_import = "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin"
    new_import = "from .search_recall_v11217 import GuangYaSearchRecallV11217Mixin"
    for path in TESTS.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        changed = False
        if old_class in text:
            text = text.replace(old_class, new_class)
            changed = True
        # 只有断言 BILINGUAL 源码 import 的测试才替换，不能改真实 manual 模块断言。
        if old_import in text and ("BILINGUAL" in text or "bilingual" in path.name):
            text = text.replace(old_import, new_import)
            changed = True
        if changed:
            path.write_text(text, encoding="utf-8")

    behavior = TESTS / "test_movie_bilingual_identity_v11216.py"
    replace(
        behavior,
        '"GuangYaManualCheckV11211Mixin": _Base,',
        '"GuangYaSearchRecallV11217Mixin": _Base,',
    )


if __name__ == "__main__":
    main()
