from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"

text = ENTRY.read_text(encoding="utf-8")
import_line = "from .gying_alias_query_v11212 import GuangYaGyingAliasQueryV11212Mixin\n"
anchor = "from .movie_identity_v1129 import GuangYaMovieIdentityV1129Mixin\n"
if import_line not in text:
    if anchor not in text:
        raise RuntimeError("movie identity import anchor missing")
    text = text.replace(anchor, anchor + import_line, 1)

mro_line = "    GuangYaGyingAliasQueryV11212Mixin,\n"
mro_anchor = "    GuangYaMovieIdentityV1129Mixin,\n"
head = text.split("class GuangYaTransferAssistant(", 1)[1].split("):", 1)[0]
if "GuangYaGyingAliasQueryV11212Mixin" not in head:
    text = text.replace(mro_anchor, mro_anchor + mro_line, 1)

ENTRY.write_text(text, encoding="utf-8")
