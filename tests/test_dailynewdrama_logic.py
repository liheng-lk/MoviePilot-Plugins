import ast
import datetime
import json
import re
import unittest
import xml.dom.minidom
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugins.v2/dailynewdrama/__init__.py"
SOURCE_TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE_TEXT)


def load_top_level_helpers():
    """从插件源码提取不依赖 MoviePilot 运行环境的纯函数。"""
    names = {
        "_parse_date_value",
        "_parse_indexes_value",
        "_xml_tag_value",
        "_parse_douban_rss",
        "_format_air_timing_value",
    }
    functions = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "datetime": datetime,
        "re": re,
        "xml": xml,
        "parsedate_to_datetime": parsedate_to_datetime,
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def load_class_method(name: str):
    """把 DailyNewDrama 的一个普通方法提取为可对假 self 调用的函数。"""
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == "DailyNewDrama":
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == name:
                    fn.decorator_list = []
                    module = ast.Module(body=[fn], type_ignores=[])
                    ast.fix_missing_locations(module)
                    namespace = {
                        "datetime": datetime,
                        "Any": Any,
                        "Dict": Dict,
                        "List": List,
                        "Optional": Optional,
                        "Tuple": Tuple,
                        "_parse_date_value": HELPERS["_parse_date_value"],
                    }
                    exec(compile(module, str(SOURCE), "exec"), namespace)
                    return namespace[name]
    raise AssertionError(f"method not found: {name}")


def class_assignments():
    """读取 DailyNewDrama 类的常量元数据。"""
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == "DailyNewDrama":
            result = {}
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                    try:
                        result[item.targets[0].id] = ast.literal_eval(item.value)
                    except (ValueError, TypeError):
                        pass
            return result
    raise AssertionError("DailyNewDrama class not found")


HELPERS = load_top_level_helpers()


class DummyConfig:
    """给日期窗口纯逻辑方法提供最小 self。"""

    _coming_days = 30
    _recent_days = 21


class DailyNewDramaTests(unittest.TestCase):
    """每日新剧助手不依赖 MoviePilot 运行环境的核心回归测试。"""

    def test_index_parser(self):
        parse = HELPERS["_parse_indexes_value"]
        self.assertEqual(parse("1,3"), [1, 3])
        self.assertEqual(parse("1-3"), [1, 2, 3])
        self.assertEqual(parse("3-1"), [1, 2, 3])
        self.assertEqual(parse("1， 3 5"), [1, 3, 5])
        self.assertEqual(parse("0,x,-1"), [])
        self.assertEqual(parse("1-999"), [])

    def test_date_parser(self):
        parse = HELPERS["_parse_date_value"]
        self.assertEqual(parse("2026-08-12"), datetime.date(2026, 8, 12))
        self.assertEqual(parse("2026-08-12T08:30:00"), datetime.date(2026, 8, 12))
        self.assertEqual(parse("Wed, 12 Aug 2026 00:00:00 GMT"), datetime.date(2026, 8, 12))
        self.assertIsNone(parse("not-a-date"))

    def test_coming_rss_uses_pubdate_as_air_date(self):
        parse = HELPERS["_parse_douban_rss"]
        xml_text = """<rss><channel><item>
        <title>测试待播剧</title>
        <link>https://movie.douban.com/subject/1234567/</link>
        <pubDate>Wed, 12 Aug 2026 00:00:00 GMT</pubDate>
        <description><![CDATA[想看人数：1000]]></description>
        </item></channel></rss>"""
        item = parse(xml_text, "coming")[0]
        self.assertEqual(item["title"], "测试待播剧")
        self.assertEqual(item["doubanid"], "1234567")
        self.assertEqual(item["year"], 2026)
        self.assertEqual(item["air_date"], "2026-08-12")
        self.assertEqual(item["source"], "coming")

    def test_hot_rss_pubdate_is_not_first_air_date_or_year(self):
        parse = HELPERS["_parse_douban_rss"]
        xml_text = """<rss><channel><item>
        <title>老剧仍然热门</title>
        <link>https://movie.douban.com/subject/7654321/</link>
        <pubDate>Wed, 12 Aug 2026 00:00:00 GMT</pubDate>
        <description><![CDATA[类型：剧情 / 地区：中国大陆]]></description>
        </item></channel></rss>"""
        item = parse(xml_text, "hot")[0]
        self.assertEqual(item["doubanid"], "7654321")
        self.assertEqual(item["air_date"], "")
        self.assertIsNone(item["year"])
        self.assertEqual(item["rss_pub_date"], "2026-08-12")

    def test_date_windows(self):
        eligible = load_class_method("_eligible_by_date")
        today = datetime.date(2026, 8, 12)
        dummy = DummyConfig()
        self.assertTrue(eligible(dummy, "coming", datetime.date(2026, 9, 1), today))
        self.assertFalse(eligible(dummy, "coming", datetime.date(2026, 10, 1), today))
        self.assertTrue(eligible(dummy, "hot", datetime.date(2026, 8, 1), today))
        self.assertFalse(eligible(dummy, "hot", datetime.date(2026, 7, 1), today))
        self.assertFalse(eligible(dummy, "hot", None, today))

    def test_air_timing_format(self):
        fmt = HELPERS["_format_air_timing_value"]
        today = datetime.date(2026, 8, 12)
        self.assertEqual(fmt(today, today), "今天开播")
        self.assertIn("3天后", fmt(datetime.date(2026, 8, 15), today))
        self.assertIn("已开播3天", fmt(datetime.date(2026, 8, 9), today))
        self.assertEqual(fmt(None, today), "日期待定")

    def test_runtime_source_and_filter_contract(self):
        self.assertIn('/douban/tv/coming/time/', SOURCE_TEXT)
        self.assertIn('/douban/movie/weekly/tv_hot', SOURCE_TEXT)
        self.assertIn('get_no_exists_info', SOURCE_TEXT)
        self.assertIn('subscribe_chain.exists', SOURCE_TEXT)
        self.assertIn('candidate_batches', SOURCE_TEXT)
        self.assertIn('notified_history', SOURCE_TEXT)
        self.assertIn('|sub|{batch_id}|', SOURCE_TEXT)

    def test_subscription_checks_real_add_result(self):
        self.assertIn('sid, err_msg = subscribe_chain.add(', SOURCE_TEXT)
        self.assertIn('message=False', SOURCE_TEXT)
        self.assertIn('if sid:', SOURCE_TEXT)

    def test_public_methods_have_docstrings(self):
        required = {
            "init_plugin",
            "get_state",
            "get_command",
            "get_service",
            "get_api",
            "get_form",
            "get_page",
            "stop_service",
            "api_refresh",
            "api_subscribe",
            "command_action",
            "message_action",
            "refresh_and_notify",
        }
        for node in TREE.body:
            if isinstance(node, ast.ClassDef) and node.name == "DailyNewDrama":
                methods = {fn.name: fn for fn in node.body if isinstance(fn, ast.FunctionDef)}
                self.assertTrue(required.issubset(methods))
                for name in required:
                    self.assertTrue(ast.get_docstring(methods[name]), f"{name} missing docstring")
                break
        else:
            self.fail("DailyNewDrama class not found")

    def test_metadata_is_consistent(self):
        attrs = class_assignments()
        package = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))["DailyNewDrama"]
        index = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["DailyNewDrama"]
        local = json.loads((ROOT / "plugins.v2/dailynewdrama/plugin.json").read_text(encoding="utf-8"))
        for meta in (package, index, local):
            self.assertEqual(meta["name"], attrs["plugin_name"])
            self.assertEqual(meta["description"], attrs["plugin_desc"])
            self.assertEqual(meta["version"], attrs["plugin_version"])
            self.assertEqual(meta["icon"], attrs["plugin_icon"])
            self.assertEqual(meta["author"], attrs["plugin_author"])
            self.assertEqual(meta["system_version"], ">=2.5.7")


if __name__ == "__main__":
    unittest.main()
