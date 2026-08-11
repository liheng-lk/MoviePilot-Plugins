import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugins.v2/dailynewdrama/__init__.py'

def load_parse_indexes():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == 'DailyNewDrama':
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == '_parse_indexes':
                    fn.decorator_list = []
                    module = ast.Module(body=[fn], type_ignores=[])
                    ast.fix_missing_locations(module)
                    ns = {'re': re, 'List': list}
                    exec(compile(module, str(SOURCE), 'exec'), ns)
                    return ns['_parse_indexes']
    raise AssertionError('_parse_indexes not found')

class DailyNewDramaTests(unittest.TestCase):
    def test_index_parser(self):
        parse = load_parse_indexes()
        self.assertEqual(parse('1,3'), [1, 3])
        self.assertEqual(parse('1-3'), [1, 2, 3])
        self.assertEqual(parse('3-1'), [1, 2, 3])
        self.assertEqual(parse('1， 3 5'), [1, 3, 5])
        self.assertEqual(parse('0,x,-1'), [])

    def test_batch_safe_callbacks_present(self):
        text = SOURCE.read_text(encoding='utf-8')
        self.assertIn('candidate_batches', text)
        self.assertIn('|sub|{batch_id}|', text)
        self.assertIn('该推荐批次已过期', text)

    def test_runtime_guards_present(self):
        text = SOURCE.read_text(encoding='utf-8')
        self.assertIn('处理候选条目失败', text)
        self.assertIn('过滤无 TMDB ID 条目', text)
        self.assertIn('get_no_exists_info', text)
        self.assertIn('subscribe_chain.exists', text)

    def test_plugin_indexes(self):
        for name in ('plugin.json', 'package.v2.json'):
            data = json.loads((ROOT / name).read_text(encoding='utf-8'))
            self.assertIn('DailyNewDrama', data)
            self.assertIn('ShukGuangYaDisk', data)

if __name__ == '__main__':
    unittest.main()
