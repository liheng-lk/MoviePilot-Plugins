import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "plugins.v2" / "shukguangyadisk" / "guangya_api.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def method_source(name: str) -> str:
    """返回 GuangYaApi 指定方法源码。"""
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"missing method: {name}")


class GuangYaUploadResilienceTests(unittest.TestCase):
    """锁定上传误判、陈旧目录和重复上传的回归行为。"""

    def test_stale_folder_142_recovers_and_retries_once(self):
        code = method_source("_get_upload_token_with_folder_recovery")
        self.assertIn('response.get("code") != 142', code)
        self.assertIn("_recover_upload_folder_id", code)
        self.assertEqual(code.count("self.client.get_upload_token("), 2)

    def test_folder_recovery_invalidates_cache_before_lookup(self):
        code = method_source("_recover_upload_folder_id")
        invalidate_pos = code.index("_invalidate_path_cache")
        lookup_pos = code.index("_path_to_id")
        self.assertLess(invalidate_pos, lookup_pos)
        self.assertIn("self.get_folder", code)

    def test_missing_task_code_switches_to_visibility_confirmation(self):
        code = method_source("_wait_task_done")
        self.assertIn("self._is_task_missing(status_response)", code)
        self.assertIn("self._is_task_missing(info_response)", code)
        self.assertIn("转由目标文件可见性确认", code)

    def test_upload_is_idempotent_before_network_upload(self):
        code = method_source("_upload_single_file")
        existing_pos = code.index("_find_existing_uploaded_item")
        hash_pos = code.index("hash_md5 = md5()")
        token_pos = code.index("_get_upload_token_with_folder_recovery")
        self.assertLess(existing_pos, hash_pos)
        self.assertLess(existing_pos, token_pos)
        self.assertIn("跳过重复上传", code)

    def test_visibility_confirmation_window_is_long_enough(self):
        node = next(
            n for n in ast.walk(TREE)
            if isinstance(n, ast.FunctionDef) and n.name == "_confirm_uploaded_item"
        )
        defaults = node.args.defaults
        values = [ast.literal_eval(v) for v in defaults]
        self.assertIn(90, values)
        self.assertIn(1.0, values)

    def test_final_failure_message_reflects_extended_confirmation(self):
        code = method_source("_upload_single_file")
        self.assertIn("上传后 90 秒仍未确认目标文件", code)


if __name__ == "__main__":
    unittest.main()
