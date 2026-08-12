import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins.v2' / 'magnetprioritysubscribe'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, PLUGIN / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load('mps_core', 'core.py')


class MagnetPriorityCoreTests(unittest.TestCase):
    def test_hex_magnet(self):
        h = '0123456789ABCDEF0123456789ABCDEF01234567'
        self.assertEqual(core.magnet_info_hash(f'magnet:?xt=urn:btih:{h.lower()}'), h)

    def test_base32_magnet(self):
        self.assertEqual(core.magnet_info_hash('magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'), '0000000000000000000000000000000000000000')

    def test_invalid_magnets(self):
        self.assertIsNone(core.magnet_info_hash('https://example.com/a.torrent'))
        self.assertIsNone(core.magnet_info_hash('magnet:?xt=urn:btih:1234'))

    def test_chinese_subtitle_positive(self):
        for value in ['Movie 2160p CHS', 'Movie CHT', 'Movie 简繁中字', 'Movie 中文字幕', 'Movie 内封中文', 'Movie CNSUB']:
            self.assertTrue(core.has_chinese_subtitle(value), value)

    def test_chinese_subtitle_negative_wins(self):
        self.assertFalse(core.has_chinese_subtitle('Movie CHS ENG ONLY'))
        self.assertFalse(core.has_chinese_subtitle('Movie 中文字幕 无中字'))

    def test_unknown_subtitle_is_rejected(self):
        self.assertFalse(core.has_chinese_subtitle('Movie 2160p WEB-DL HEVC'))

    def test_episode_parser(self):
        season, eps = core.parse_season_episodes('Show S02E09-E12 2160p CHS')
        self.assertEqual(season, 2)
        self.assertEqual(eps, {9, 10, 11, 12})

    def test_episode_overlap(self):
        self.assertTrue(core.matches_episode_need('Show S01E09-E12 CHS', 1, [9, 10]))
        self.assertFalse(core.matches_episode_need('Show S01E01-E08 CHS', 1, [9, 10]))
        self.assertFalse(core.matches_episode_need('Show S02E09-E12 CHS', 1, [9, 10]))

    def test_season_pack_can_match_missing(self):
        self.assertTrue(core.matches_episode_need('Show S01 Complete CHS', 1, [9, 10]))

    def test_quality_score(self):
        self.assertGreater(core.score_result('Show 2160p WEB-DL HEVC HDR CHS', seeders=20), core.score_result('Show 1080p WEBRip H264 CHS', seeders=100))

    def test_select_best_hard_subtitle_gate(self):
        h1 = '0123456789ABCDEF0123456789ABCDEF01234567'
        h2 = '1123456789ABCDEF0123456789ABCDEF01234567'
        no_sub = core.normalize_result('Show S01E09-E10 2160p WEB-DL HEVC', f'magnet:?xt=urn:btih:{h1}', seeders=999)
        chinese = core.normalize_result('Show S01E09-E10 1080p WEB-DL CHS', f'magnet:?xt=urn:btih:{h2}', seeders=10)
        self.assertEqual(core.select_best([no_sub, chinese], 1, [9, 10]).info_hash, h2)

    def test_dedupe_by_infohash(self):
        h = '2123456789ABCDEF0123456789ABCDEF01234567'
        a = core.normalize_result('Show S01E09-E10 1080p CHS', f'magnet:?xt=urn:btih:{h}', seeders=1)
        b = core.normalize_result('Show S01E09-E10 2160p HEVC CHS', f'magnet:?xt=urn:btih:{h}', seeders=3)
        self.assertIn('2160p', core.select_best([a, b], 1, [9]).title)


if __name__ == '__main__':
    unittest.main()
