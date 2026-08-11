import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _Settings:
    PROXY = None


class _Logger:
    def info(self, *args, **kwargs):
        pass
    def warning(self, *args, **kwargs):
        pass


class _DummyRequest:
    pass


app = types.ModuleType("app")
core = types.ModuleType("app.core")
config = types.ModuleType("app.core.config")
config.settings = _Settings()
log = types.ModuleType("app.log")
log.logger = _Logger()
utils = types.ModuleType("app.utils")
http = types.ModuleType("app.utils.http")
http.RequestUtils = _DummyRequest
sys.modules.setdefault("app", app)
sys.modules.setdefault("app.core", core)
sys.modules.setdefault("app.core.config", config)
sys.modules.setdefault("app.log", log)
sys.modules.setdefault("app.utils", utils)
sys.modules.setdefault("app.utils.http", http)

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins.v2" / "dailynewdrama" / "platform_sources.py"
spec = importlib.util.spec_from_file_location("dailynewdrama_platform_sources", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class PlatformLogicTests(unittest.TestCase):
    def test_status_classification(self):
        self.assertTrue(mod._is_ongoing("更新至12集"))
        self.assertTrue(mod._is_ongoing("每周三更新"))
        self.assertFalse(mod._is_ongoing("全24集"))
        self.assertTrue(mod._is_finished("已完结"))
        self.assertTrue(mod._is_finished("全40集"))

    def test_candidate_filters_old_finished(self):
        self.assertIsNone(mod._candidate("测试", "老剧", 2019, "全40集"))
        row = mod._candidate("测试", "在播剧", 2019, "更新至10集")
        self.assertIsNotNone(row)
        self.assertTrue(row["ongoing"])
        self.assertEqual(row["source"], "platform_ongoing")

    def test_iqiyi_new_online(self):
        sample = {
            "data": {
                "list": [
                    {"albumId": "101", "name": "爱奇艺新剧", "year": mod.CURRENT_YEAR,
                     "latestOrder": 8, "videoCount": 24, "imageUrl": "https://img/1.jpg"},
                    {"albumId": "102", "name": "已完结剧", "year": mod.CURRENT_YEAR,
                     "latestOrder": 24, "videoCount": 24, "description": "全24集"},
                ]
            }
        }
        old = mod._request_json
        mod._request_json = lambda *a, **k: (sample, "mock")
        try:
            rows, via = mod.fetch_iqiyi()
        finally:
            mod._request_json = old
        self.assertEqual(via, "mock")
        self.assertTrue(any(x["title"] == "爱奇艺新剧" and x["ongoing"] for x in rows))
        # 新上线列表允许完结条目作为近期上线，但不能误标 ongoing
        finished = next(x for x in rows if x["title"] == "已完结剧")
        self.assertFalse(finished["ongoing"])

    def test_mgtv_ongoing(self):
        sample = {"data": {"hitDocs": [
            {"clipId": "m1", "title": "芒果在播", "year": mod.CURRENT_YEAR, "updateInfo": "更新至16集", "img": "x"},
            {"clipId": "m2", "title": "芒果旧剧", "year": 2018, "updateInfo": "全30集", "img": "x"},
        ]}}
        old = mod._request_json
        mod._request_json = lambda *a, **k: (sample, "mock")
        try:
            rows, _ = mod.fetch_mgtv()
        finally:
            mod._request_json = old
        self.assertEqual([x["title"] for x in rows], ["芒果在播"])
        self.assertTrue(rows[0]["ongoing"])

    def test_bilibili_unfinished(self):
        sample = {"data": {"list": [
            {"media_id": 11, "title": "B站在播", "index_show": "更新至第6集", "cover": "x"}
        ]}}
        old = mod._request_json
        mod._request_json = lambda *a, **k: (sample, "mock")
        try:
            rows, _ = mod.fetch_bilibili()
        finally:
            mod._request_json = old
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "哔哩哔哩")
        self.assertTrue(rows[0]["ongoing"])

    def test_youku_category_session(self):
        first = {"data": {"filterData": {"session": {"a": 1}}}}
        second = {"data": {"filterData": {"listData": [
            {"title": "优酷在播", "videoLink": "https://v.youku.com/v_show/id_x.html?s=S1", "rightTagText": str(mod.CURRENT_YEAR), "summary": "更新至9集", "img": "x"}
        ]}}}
        calls = iter([(first, "mock1"), (second, "mock2")])
        old = mod._request_json
        mod._request_json = lambda *a, **k: next(calls)
        try:
            rows, via = mod.fetch_youku()
        finally:
            mod._request_json = old
        self.assertEqual(via, "mock2")
        self.assertEqual(rows[0]["title"], "优酷在播")
        self.assertTrue(rows[0]["ongoing"])

    def test_tencent_card_parse(self):
        sample = {"data": {"module_list_datas": [{"module_datas": [{"item_data_lists": {"item_datas": [
            {"id": "tx1", "item_params": {"cid": "tx1", "title": "腾讯在播", "episode_updated": "更新至10集", "uni_imgtag": '{"tag_2":{"text":"%s"},"tag_4":{"text":"更新至10集"}}' % mod.CURRENT_YEAR}}
        ]}}]}]}}
        old = mod._request_json
        mod._request_json = lambda *a, **k: (sample, "mock")
        try:
            rows, _ = mod.fetch_tencent()
        finally:
            mod._request_json = old
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["platform"], "腾讯视频")
        self.assertTrue(rows[0]["ongoing"])

    def test_provider_registry_has_all_five(self):
        self.assertEqual(set(mod.PROVIDERS), {"tencent", "iqiyi", "youku", "mgtv", "bilibili"})


if __name__ == "__main__":
    unittest.main()
