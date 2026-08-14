import ast
from pathlib import Path
text=(Path(__file__).resolve().parents[1]/'plugins.v2/dailynewdrama/__init__.py').read_text(encoding='utf-8')
tree=ast.parse(text)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DailyNewDrama')
fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='api_subscribe')
assert [a.arg for a in fn.args.args]==['self','indexes','batch_id','apikey']
assert '"apikey": settings.API_TOKEN' in text
assert 'apikey != settings.API_TOKEN' in text
