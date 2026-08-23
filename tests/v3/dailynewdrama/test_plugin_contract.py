from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[3]
V3=ROOT/"plugins.v3"/"dailynewdrama"
text=(V3/"__init__.py").read_text(encoding="utf-8")
platform=(V3/"platform_sources.py").read_text(encoding="utf-8")
idx=json.loads((ROOT/"package.v3.json").read_text(encoding="utf-8"))["DailyNewDrama"]
v2=json.loads((ROOT/"package.v2.json").read_text(encoding="utf-8"))["DailyNewDrama"]
assert "plugin_version = \"3.0.1\"" in text
assert idx["version"]=="3.0.1" and idx["system_version"]==">=3.0.0"
assert v2.get("v3") is False
for old in ("from app.core.config import","from app.core.context import","from app.core.event import","from app.core.metainfo import","from app.log import","from app.utils.http import"):
    assert old not in text
assert "from app.sdk.config import settings" in text
assert "from app.sdk.media import MediaInfo, MetaInfo" in text
assert "from app.sdk.events import Event, eventmanager" in text
assert "from app.sdk.logging import logger" in text
assert "from app.sdk.network import RequestUtils" in text
assert "from app.sdk.config import settings" in platform
assert "from app.sdk.logging import logger" in platform
assert "from app.sdk.network import RequestUtils" in platform
assert "recognize_media(meta=meta, tmdbid=" not in text
assert "recognize_media(meta=meta, doubanid=" not in text
assert "media_source=subscribe_media_source" in text
assert "media_id=str(subscribe_media_id)" in text
assert "\"method\": \"get\"" in text
assert "\"apikey\": settings.API_TOKEN" in text

# 3.0.1 regression contracts
assert "def _media_library_has_content" in text
assert "suppress_recent: bool = False" in text
assert "chunk_size = 8" in text
assert text.count("_media_library_has_content(mediainfo, exist_flag, no_exists)") == 2
assert "完整候选列表" in text

import ast
tree = ast.parse(text)
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_media_library_has_content")
node.returns = None
for arg in node.args.args:
    arg.annotation = None
mod = ast.Module(body=[node], type_ignores=[])
ast.fix_missing_locations(mod)
ns = {}
exec(compile(mod, str(V3 / "__init__.py"), "exec"), ns)
helper = ns["_media_library_has_content"]
class _Media:
    seasons = {1: [1, 2, 3], 2: [1, 2]}
class _Missing:
    def __init__(self, episodes): self.episodes = episodes
assert helper(_Media(), True, {}) is True
assert helper(_Media(), False, {"tmdb:1": {1: _Missing([]), 2: _Missing([])}}) is False
assert helper(_Media(), False, {"tmdb:1": {1: _Missing([3]), 2: _Missing([])}}) is True
assert helper(_Media(), False, {"tmdb:1": {2: _Missing([])}}) is True
