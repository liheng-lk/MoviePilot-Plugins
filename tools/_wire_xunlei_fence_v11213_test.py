from pathlib import Path

path = Path('tests/v3/guangyatransferassistant/test_xunlei_season_fence_v11210.py')
text = path.read_text(encoding='utf-8')
old = '''    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
    alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
    ast.parse(manual, filename=str(PLUGIN / "manual_check_v11211.py"))
    ast.parse(alias, filename=str(PLUGIN / "gying_alias_query_v11212.py"))
    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in movie
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie
    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in manual
    assert "class GuangYaManualCheckV11211Mixin(GuangYaGyingAliasQueryV11212Mixin):" in manual
    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in alias
    assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias
'''
new = '''    manual = (PLUGIN / "manual_check_v11211.py").read_text(encoding="utf-8")
    fence = (PLUGIN / "xunlei_existing_fence_v11213.py").read_text(encoding="utf-8")
    alias = (PLUGIN / "gying_alias_query_v11212.py").read_text(encoding="utf-8")
    ast.parse(manual, filename=str(PLUGIN / "manual_check_v11211.py"))
    ast.parse(fence, filename=str(PLUGIN / "xunlei_existing_fence_v11213.py"))
    ast.parse(alias, filename=str(PLUGIN / "gying_alias_query_v11212.py"))
    assert "from .manual_check_v11211 import GuangYaManualCheckV11211Mixin" in movie
    assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie
    assert "from .xunlei_existing_fence_v11213 import GuangYaXunleiExistingEpisodeFenceV11213Mixin" in manual
    assert "class GuangYaManualCheckV11211Mixin(GuangYaXunleiExistingEpisodeFenceV11213Mixin):" in manual
    assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in fence
    assert "class GuangYaXunleiExistingEpisodeFenceV11213Mixin(GuangYaGyingAliasQueryV11212Mixin):" in fence
    assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in alias
    assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias
'''
if old not in text:
    raise SystemExit('expected v1.12.10 wiring contract not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
