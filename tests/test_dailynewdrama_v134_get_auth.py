from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'plugins.v2/dailynewdrama/__init__.py').read_text(encoding='utf-8')
pos=text.index('"api": "plugin/DailyNewDrama/subscribe"'); block=text[max(0,pos-250):pos+650]
assert '"method": "get"' in block
assert '"apikey": settings.API_TOKEN' in block
pos2=text.index('"path": "/subscribe"'); route=text[pos2:pos2+350]
assert '"methods": ["GET"]' in route
assert 'plugin_version = "1.3.6"' in text
assert json.loads((ROOT/'package.v2.json').read_text())['DailyNewDrama']['version']=='1.3.6'
assert json.loads((ROOT/'plugin.json').read_text())['DailyNewDrama']['version']=='1.3.6'
assert json.loads((ROOT/'plugins.v2/dailynewdrama/plugin.json').read_text())['version']=='1.3.6'
