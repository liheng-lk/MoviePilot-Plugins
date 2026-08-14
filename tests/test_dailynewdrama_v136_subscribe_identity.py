from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'plugins.v2/dailynewdrama/__init__.py').read_text(encoding='utf-8')
assert 'plugin_version = "1.3.6"' in text
block=text[text.index('sid, err_msg = subscribe_chain.add(')-800:text.index('sid, err_msg = subscribe_chain.add(')+900]
assert 'tmdbid=' not in block
assert 'doubanid=' not in block
assert 'media_source=subscribe_media_source' in block
assert 'media_id=str(subscribe_media_id)' in block
assert '【每日新剧助手】【订阅链诊断】准备创建订阅' in text
assert json.loads((ROOT/'package.v2.json').read_text())['DailyNewDrama']['version']=='1.3.6'
assert json.loads((ROOT/'plugin.json').read_text())['DailyNewDrama']['version']=='1.3.6'
assert json.loads((ROOT/'plugins.v2/dailynewdrama/plugin.json').read_text())['version']=='1.3.6'
