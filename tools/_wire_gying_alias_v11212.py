from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
MOVIE = PLUGIN / "movie_identity_v1129.py"
MANUAL = PLUGIN / "manual_check_v11211.py"
ALIAS = PLUGIN / "gying_alias_query_v11212.py"
SEASON = PLUGIN / "xunlei_season_fence_v11210.py"

entry = ENTRY.read_text(encoding="utf-8")
movie = MOVIE.read_text(encoding="utf-8")
manual = MANUAL.read_text(encoding="utf-8")
alias = ALIAS.read_text(encoding="utf-8")
season = SEASON.read_text(encoding="utf-8")

head = entry.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
assert "GuangYaGyingAliasQueryV11212Mixin" not in head
assert "class GuangYaMovieIdentityV1129Mixin(GuangYaManualCheckV11211Mixin):" in movie
assert "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin" in manual
assert "class GuangYaManualCheckV11211Mixin(GuangYaGyingAliasQueryV11212Mixin):" in manual
assert "from .xunlei_season_fence_v11210 import GuangYaXunleiSeasonFenceV11210Mixin" in alias
assert "class GuangYaGyingAliasQueryV11212Mixin(GuangYaXunleiSeasonFenceV11210Mixin):" in alias
assert 'plugin_version = "1.12.10"' in season
assert 'plugin_version = "1.12.11"' in manual
assert 'plugin_version = "1.12.12"' in alias
