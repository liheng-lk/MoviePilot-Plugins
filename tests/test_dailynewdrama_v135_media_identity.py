from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'plugins.v2/dailynewdrama/__init__.py').read_text(encoding='utf-8')
assert 'from app.schemas.types import EventType, MediaSource' in text
assert 'plugin_version = "1.3.5"' in text
assert 'recognize_media(meta=meta, tmdbid=' not in text
assert 'recognize_media(meta=meta, doubanid=' not in text
assert 'media_source=MediaSource.TMDB, media_id=str(item.get("tmdbid"))' in text
assert 'media_source=MediaSource.TMDB, media_id=str(tmdbinfo.get("id"))' in text
assert 'media_source=MediaSource.Douban, media_id=str(doubanid)' in text
assert json.loads((ROOT/'package.v2.json').read_text())['DailyNewDrama']['version']=='1.3.5'
assert json.loads((ROOT/'plugin.json').read_text())['DailyNewDrama']['version']=='1.3.5'
assert json.loads((ROOT/'plugins.v2/dailynewdrama/plugin.json').read_text())['version']=='1.3.5'
