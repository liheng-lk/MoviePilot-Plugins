import ast, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'plugins.v2/dailynewdrama/__init__.py'
tree=ast.parse(SRC.read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DailyNewDrama')
fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='api_subscribe')
args=[a.arg for a in fn.args.args]
assert args==['self','indexes','batch_id'], args
text=SRC.read_text(encoding='utf-8')
block=text[text.index('def api_subscribe'):text.index('def _remove_current_candidates')]
assert 'payload: dict' not in block
assert '"api": "plugin/DailyNewDrama/subscribe"' in text
assert '"params": {"indexes":' in text
assert 'plugin_version = "1.3.1"' in text
assert json.loads((ROOT/'package.v2.json').read_text())['DailyNewDrama']['version']=='1.3.1'
assert json.loads((ROOT/'plugin.json').read_text())['DailyNewDrama']['version']=='1.3.1'
assert json.loads((ROOT/'plugins.v2/dailynewdrama/plugin.json').read_text())['version']=='1.3.1'
