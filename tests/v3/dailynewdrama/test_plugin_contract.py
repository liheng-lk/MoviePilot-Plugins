from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[3]
V3=ROOT/"plugins.v3"/"dailynewdrama"
text=(V3/"__init__.py").read_text(encoding="utf-8")
platform=(V3/"platform_sources.py").read_text(encoding="utf-8")
idx=json.loads((ROOT/"package.v3.json").read_text(encoding="utf-8"))["DailyNewDrama"]
v2=json.loads((ROOT/"package.v2.json").read_text(encoding="utf-8"))["DailyNewDrama"]
assert "plugin_version = \"3.0.0\"" in text
assert idx["version"]=="3.0.0" and idx["system_version"]==">=3.0.0"
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
