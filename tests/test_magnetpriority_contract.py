import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INIT = (ROOT / 'plugins.v2' / 'magnetprioritysubscribe' / '__init__.py').read_text(encoding='utf-8')


class MagnetPriorityContractTests(unittest.TestCase):
    def test_indexes_are_consistent(self):
        root_a = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))['MagnetPrioritySubscribe']
        root_b = json.loads((ROOT / 'package.v2.json').read_text(encoding='utf-8'))['MagnetPrioritySubscribe']
        local = json.loads((ROOT / 'plugins.v2' / 'magnetprioritysubscribe' / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(root_a['version'], root_b['version'])
        self.assertEqual(root_a['version'], local['version'])
        self.assertEqual(root_a['name'], local['name'])
        self.assertEqual(root_a['description'], local['description'])
        self.assertIn('1.0-beta2', INIT)

    def test_beta_defaults_to_safe_dry_run(self):
        self.assertIn('"dry_run": True', INIT)
        self.assertIn('beta2 仍不抑制 MoviePilot 原生搜索/下载', INIT)

    def test_builtin_source_configuration_present(self):
        self.assertIn('jackett_enabled', INIT)
        self.assertIn('prowlarr_enabled', INIT)
        self.assertIn('torznab_enabled', INIT)
        self.assertIn('build_sources', INIT)

    def test_subtitle_gate_is_hard(self):
        core = (ROOT / 'plugins.v2' / 'magnetprioritysubscribe' / 'core.py').read_text(encoding='utf-8')
        self.assertIn('not item.chinese_subtitle', core)

    def test_guangya_requires_task_id(self):
        code = (ROOT / 'plugins.v2' / 'magnetprioritysubscribe' / 'guangya_offline.py').read_text(encoding='utf-8')
        self.assertIn('响应缺少 taskId', code)

    def test_failure_path_is_fail_open(self):
        self.assertIn('已放行 MoviePilot 原生链路', INIT)
        self.assertIn('status="fallback"', INIT)


if __name__ == '__main__':
    unittest.main()
