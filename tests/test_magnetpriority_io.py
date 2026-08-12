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

# MoviePilot 运行环境自带 requests；仓库 CI 保持最小依赖，因此这里提供最小桩。
requests_stub = types.ModuleType('requests')
class RequestException(Exception):
    pass
class Session:
    pass
requests_stub.RequestException = RequestException
requests_stub.Session = Session
sys.modules.setdefault('requests', requests_stub)


def load(name, filename):
    full = f'{PKG}.{name}'
    spec = importlib.util.spec_from_file_location(full, PLUGIN / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


core = load('core', 'core.py')
torznab = load('torznab', 'torznab.py')
sources = load('sources', 'sources.py')
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
        src = torznab.TorznabSource('x', 'http://indexer/api', 'k')
        session = FakeSession([FakeResponse(status=429)])
        with self.assertRaises(torznab.TorznabError):
            torznab.search_torznab(src, 'Show', session=session)

    def test_query_contains_tv_fields(self):
        src = torznab.TorznabSource('x', 'http://indexer/torznab/api', 'k')
        session = FakeSession([FakeResponse(status=200, text=self.XML)])
        torznab.search_torznab(src, 'Show', season=1, episode=9, tmdb_id=123, session=session)
        url = session.calls[0][1]
        self.assertIn('season=1', url)
        self.assertIn('ep=9', url)
        self.assertIn('tmdbid=123', url)
        self.assertIn('apikey=k', url)

    def test_complete_api_url_is_not_rewritten(self):
        endpoint = 'http://jackett:9117/api/v2.0/indexers/all/results/torznab/api'
        src = torznab.TorznabSource('Jackett', endpoint, 'secret')
        url = torznab.build_search_url(src, 'Show')
        self.assertTrue(url.startswith(endpoint + '?'))
        self.assertNotIn('/api/api', url)

    def test_existing_query_string_is_preserved(self):
        src = torznab.TorznabSource('x', 'http://host/feed?cat=5000', '')
        url = torznab.build_search_url(src, 'Show')
        self.assertIn('cat=5000', url)
        self.assertIn('q=Show', url)

    def test_invalid_url_rejected(self):
        with self.assertRaises(torznab.TorznabError):
            torznab.build_search_url(torznab.TorznabSource('bad', 'not-a-url'), 'Show')


class BuiltinSourceTests(unittest.TestCase):
    def test_jackett_preset(self):
        result = sources.build_sources({
            'jackett_enabled': True,
            'jackett_api_key': 'JKEY',
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, 'Jackett')
        self.assertEqual(result[0].url, sources.JACKETT_ALL_DEFAULT)
        self.assertEqual(result[0].api_key, 'JKEY')

    def test_prowlarr_preset_requires_feed_url(self):
        self.assertEqual(sources.build_sources({'prowlarr_enabled': True}), [])
        result = sources.build_sources({
            'prowlarr_enabled': True,
            'prowlarr_torznab_url': 'http://prowlarr/feed',
            'prowlarr_api_key': 'PKEY',
        })
        self.assertEqual(result[0].name, 'Prowlarr')
        self.assertEqual(result[0].url, 'http://prowlarr/feed')

    def test_generic_torznab_preset(self):
        result = sources.build_sources({
            'torznab_enabled': True,
            'torznab_name': 'Mine',
            'torznab_url': 'http://mine/api',
        })
        self.assertEqual(result[0].name, 'Mine')

    def test_advanced_json_and_dedupe(self):
        result = sources.build_sources({
            'torznab_enabled': True,
            'torznab_name': 'Mine',
            'torznab_url': 'http://mine/api',
            'torznab_sources_json': '[{"name":"dup","url":"http://mine/api"},{"name":"two","url":"http://two/api"}]',
        })
        self.assertEqual([item.name for item in result], ['Mine', 'two'])

    def test_bad_advanced_json_is_error(self):
        with self.assertRaises(RuntimeError):
            sources.build_sources({'torznab_sources_json': '{bad'})


class GuangYaOfflineTests(unittest.TestCase):
    def cfg(self):
        return guangya.GuangYaOfflineConfig('a', 'r', 'd')

    def test_create_task_requires_taskid(self):
        s = FakeSession([FakeResponse(json_data={'msg': 'success', 'data': {}})])
        with self.assertRaises(guangya.GuangYaOfflineError):
            guangya.GuangYaOfflineClient(self.cfg(), session=s).create_task('magnet:?xt=urn:btih:x', 'p', 'name')

    def test_create_task_success(self):
        s = FakeSession([FakeResponse(json_data={'msg': 'success', 'data': {'taskId': 'T1'}})])
        self.assertEqual(guangya.GuangYaOfflineClient(self.cfg(), session=s).create_task('m', 'p', 'name'), 'T1')
        self.assertTrue(s.calls[0][1].endswith('/cloudcollection/v1/create_task'))

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
        with self.assertRaises(guangya.GuangYaOfflineError):
            guangya.GuangYaOfflineClient(self.cfg(), session=s).create_task('m', 'p', 'name')

    def test_resolve_magnet(self):
        s = FakeSession([FakeResponse(json_data={'msg': '', 'data': {'resType': 3, 'btResInfo': {'infoHash': 'x'}}})])
        self.assertEqual(guangya.GuangYaOfflineClient(self.cfg(), session=s).resolve_magnet('m')['resType'], 3)

    def test_list_task(self):
        s = FakeSession([FakeResponse(json_data={'msg': 'success', 'data': {'list': [{'taskId': 'T1', 'status': 1, 'progress': 50}]}})])
        self.assertEqual(guangya.GuangYaOfflineClient(self.cfg(), session=s).list_task('T1')['progress'], 50)


if __name__ == '__main__':
    unittest.main()
