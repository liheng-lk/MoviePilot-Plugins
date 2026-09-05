from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
TESTS = ROOT / "tests" / "v3" / "guangyatransferassistant"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"contract marker missing: {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


manual_test = TESTS / "test_manual_check_v11211.py"
replace_once(
    manual_test,
    '        "GuangYaXunleiSeasonFenceV11210Mixin": _Base,\n',
    '        "GuangYaGyingAliasQueryV11212Mixin": _Base,\n',
)
replace_once(
    manual_test,
    '''    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in SOURCE\n    assert "class GuangYaManualCheckV11211Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in SOURCE\n    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in MOVIE\n    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in MOVIE\n''',
    '''    alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")\n    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in SOURCE\n    assert "class GuangYaManualCheckV11211Mixin(GuangYaGyingAliasQueryV11212Mixin):" in SOURCE\n    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in alias\n    assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias\n    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in MOVIE\n    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in MOVIE\n''',
)

season_test = TESTS / "test_xunlei_season_fence_v11210.py"
replace_once(
    season_test,
    '''    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")\n    ast.parse(manual, filename=str(PLUGIN / "manual_check_v11211.py"))\n    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in movie\n    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie\n    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in manual\n    assert "class GuangYaManualCheckV11211Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in manual\n''',
    '''    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")\n    alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")\n    ast.parse(manual, filename=str(PLUGIN / "manual_check_v11211.py"))\n    ast.parse(alias, filename=str(PLUGIN / "gying_alias_query_v11212.py"))\n    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in movie\n    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie\n    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in manual\n    assert "class GuangYaManualCheckV11211Mixin(GuangYaGyingAliasQueryV11212Mixin):" in manual\n    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in alias\n    assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias\n''',
)

entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
movie = (PLUGIN / "movie_identity_v1129.py").read_text(encoding="utf-8")
manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
season = (PLUGIN / "xunlei_season_fence_v11210.py").read_text(encoding="utf-8")
head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]

assert "GuangYaGyingAliasQueryV11212Mixin" not in head
assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie
assert "class GuangYaManualCheckV11211Mixin(GuangYaGyingAliasQueryV11212Mixin):" in manual
assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias
assert 'plugin_version = "1.12.10"' in season
assert 'plugin_version = "1.12.11"' in manual
assert 'plugin_version = "1.12.12"' in alias
