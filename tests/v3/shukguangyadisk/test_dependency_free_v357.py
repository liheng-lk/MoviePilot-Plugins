from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
LEGACY = (PLUGIN / "guangya_client_legacy.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("oss_native_v357_test", PLUGIN / "oss_native_v357.py")
assert spec and spec.loader
OSS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(OSS)


class DependencyFreeV357Tests(unittest.TestCase):
    def test_v3_shuk_has_no_dependency_manifest(self):
        self.assertFalse((PLUGIN / "pyproject.toml").exists())
        self.assertFalse((PLUGIN / "requirements.txt").exists())

    def test_oss2_is_not_imported_by_v3_runtime(self):
        self.assertNotIn("import oss2", LEGACY)
        self.assertIn("_native_oss_multipart_upload", LEGACY)
        self.assertIn("import requests", LEGACY)

    def test_virtual_host_endpoint_and_object_encoding(self):
        base, host = OSS._normalize_endpoint("oss-cn-hangzhou.aliyuncs.com", "examplebucket")
        self.assertEqual(base, "https://examplebucket.oss-cn-hangzhou.aliyuncs.com")
        self.assertEqual(host, "examplebucket.oss-cn-hangzhou.aliyuncs.com")
        key, path = OSS._object_url_path("目录/测试 01.mp4")
        self.assertEqual(key, "目录/测试 01.mp4")
        self.assertEqual(path, "/%E7%9B%AE%E5%BD%95/%E6%B5%8B%E8%AF%95%2001.mp4")

    def test_multipart_subresources_are_canonicalized(self):
        params = (("uploadId", "abc+/="), ("partNumber", "2"))
        self.assertEqual(OSS._query_string(params), "partNumber=2&uploadId=abc%2B%2F%3D")
        self.assertEqual(
            OSS._canonical_resource("bucket", "path/file.mp4", params),
            "/bucket/path/file.mp4?partNumber=2&uploadId=abc%2B%2F%3D",
        )
        self.assertEqual(OSS._query_string((("uploads", None),)), "uploads")

    def test_v1_sts_authorization_matches_known_vector(self):
        auth = OSS._authorization(
            method="PUT",
            access_key_id="testid",
            access_key_secret="testsecret",
            date="Sun, 30 Aug 2026 05:00:00 GMT",
            canonical_resource="/bucket/dir/测试.mp4?partNumber=1&uploadId=abc",
            headers={"x-oss-security-token": "token"},
            content_md5="",
            content_type="application/octet-stream",
        )
        self.assertEqual(auth, "OSS testid:fjVIrX9R+G+9JtvWEnRfQOnkEYo=")

    def test_complete_xml_keeps_part_order_and_etag(self):
        payload = OSS._complete_xml([(1, '"etag-1"'), (2, '"etag-2"')])
        root = ET.fromstring(payload)
        rows = [
            (int(part.findtext("PartNumber")), part.findtext("ETag"))
            for part in root.findall("Part")
        ]
        self.assertEqual(rows, [(1, '"etag-1"'), (2, '"etag-2"')])

    def test_version_metadata_is_consistent(self):
        plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin_meta["version"], "3.5.7")
        self.assertEqual(package_meta["ShukGuangYaDisk"]["version"], "3.5.7")
        self.assertIn('plugin_version = "3.5.7"', ENTRY)
        self.assertIn("?v=3.5.7", REMOTE)


if __name__ == "__main__":
    unittest.main()
