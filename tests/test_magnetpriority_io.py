import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins.v2' / 'magnetprioritysubscribe'
PKG = 'mps_testpkg'
package = types.ModuleType(PKG)
package.__path__ = [str(PLUGIN)]
sys.modules.setdefault(PKG, package)


def load(name, filename):
    full = f'{PKG}.{name}'
    spec = importlib.util.spec_from_file_location(full, PLUGIN / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


core = load('core', 'core.py')
torznab = load('torznab', 'torznab.py')
guangya = load('guangya_offline', 'guangya_offline.py')


class FakeResponse:
    def __init__(self, status=200, json_data=None, text='', content=b'x'):
        self.status_code = status
        self._json = json_data or {}
        self.text = text
        self.content = content
    def json(self):
        return self._json


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def get(self, url, timeout=None):
        self.calls.append(('GET', url, timeout))
        return self.responses.pop(0)
    def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        return self.responses.pop(0)


class TorznabTests(unittest.TestCase):
    XML = '''<?xml version="1.0"?><rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>
    <item><title>Show S01E09-E10 2160p WEB-DL CHS</title>
    <link>magnet:?xt=urn:btih:0123456789ABCDEF0123456789ABCDEF01234567</link>
    <size>5000000000</size><torznab:attr name="seeders" value="33" /></item>
    </channel></rss>'''

    def test_parse_xml(self):
        out = torznab.parse_torznab_xml(self.XML, 'test')
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].chinese_subtitle)
        self.assertEqual(out[0].seeders, 33)
        self.assertEqual(out[0].episodes, (9, 10))

    def test_bad_xml(self):
        with self.assertRaises(torznab.TorznabError):
            torznab.parse_torznab_xml('<bad', 'x')

    def test_http_error(self):
        src = torznab.TorznabSource('x', 'http://indexer', 'k')
        session = FakeSession([FakeResponse(status=429)])
        with self.assertRaises(torznab.TorznabError):
            torznab.search_torznab(src, 'Show', session=session)

    def test_query_contains_tv_fields(self):
        src = torznab.TorznabSource('x', 'http://indexer', 'k')
        session = FakeSession([FakeResponse(status=200, text=self.XML)])
        torznab.search_torznab(src, 'Show', season=1, episode=9, tmdb_id=123, session=session)
        url = session.calls[0][1]
        self.assertIn('season=1', url)
        self.assertIn('ep=9', url)
        self.assertIn('tmdbid=123', url)


class GuangYaOfflineTests(unittest.TestCase):
    def cfg(self):
        return guangya.GuangYaOfflineConfig('a', 'r', 'd')

    def test_create_task_requires_taskid(self):
        s = FakeSession([FakeResponse(json_data={'msg': 'success', 'data': {}})])
        c = guangya.GuangYaOfflineClient(self.cfg(), session=s)
        with self.assertRaises(guangya.GuangYaOfflineError):
            c.create_task('magnet:?xt=urn:btih:x', 'p', 'name')

    def test_create_task_success(self):
        s = FakeSession([FakeResponse(json_data={'msg': 'success', 'data': {'taskId': 'T1'}})])
        c = guangya.GuangYaOfflineClient(self.cfg(), session=s)
        self.assertEqual(c.create_task('m', 'p', 'name'), 'T1')
        url = s.calls[0][1]
        self.assertTrue(url.endswith('/cloudcollection/v1/create_task'))

    def test_401_refresh_and_retry(self):
        s = FakeSession([
            FakeResponse(status=401, json_data={'msg': 'unauthorized'}),
            FakeResponse(status=200, json_data={'access_token': 'new-a', 'refresh_token': 'new-r'}),
            FakeResponse(status=200, json_data={'msg': 'success', 'data': {'taskId': 'T2'}}),
        ])
        cfg = self.cfg()
        c = guangya.GuangYaOfflineClient(cfg, session=s)
        self.assertEqual(c.create_task('m', 'p', 'name'), 'T2')
        self.assertEqual(cfg.access_token, 'new-a')
        self.assertEqual(cfg.refresh_token, 'new-r')
        self.assertEqual(len(s.calls), 3)

    def test_business_error_is_failure_even_http_200(self):
        s = FakeSession([FakeResponse(status=200, json_data={'msg': '任务创建失败', 'data': {}})])
        c = guangya.GuangYaOfflineClient(self.cfg(), session=s)
        with self.assertRaises(guangya.GuangYaOfflineError):
            c.create_task('m', 'p', 'name')

    def test_resolve_magnet(self):
        s = FakeSession([FakeResponse(json_data={'msg': '', 'data': {'resType': 3, 'btResInfo': {'infoHash': 'x'}}})])
        c = guangya.GuangYaOfflineClient(self.cfg(), session=s)
        self.assertEqual(c.resolve_magnet('m')['resType'], 3)

    def test_list_task(self):
        s = FakeSession([FakeResponse(json_data={'msg': 'success', 'data': {'list': [{'taskId': 'T1', 'status': 1, 'progress': 50}]}})])
        c = guangya.GuangYaOfflineClient(self.cfg(), session=s)
        self.assertEqual(c.list_task('T1')['progress'], 50)


if __name__ == '__main__':
    unittest.main()
