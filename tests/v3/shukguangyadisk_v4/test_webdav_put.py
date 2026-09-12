"""WebDAV PUT 回归测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from app.testing.bootstrap import prepare_backend

prepare_backend()

from app.plugins.shukguangyadisk import GuangyaWebDAVProvider


class _FakeApi:
    def __init__(self, existing=None):
        self.existing = existing
        self.upload_calls = []
        self.parent = SimpleNamespace(path="/media", type="dir", fileid="parent")

    def get_item(self, path: Path):
        value = str(path).replace("\\", "/")
        if value == "/media":
            return self.parent
        if value == "/media/demo.mkv":
            return self.existing
        return None

    def upload(self, parent, local_path: Path, new_name=None):
        self.upload_calls.append((parent, local_path, new_name))
        return SimpleNamespace(path=f"/media/{new_name}", name=new_name, type="file")


class WebDavPutTest(unittest.TestCase):
    def make_request(self, payload=b"video"):
        return SimpleNamespace(_body=payload)

    def test_put_new_file_returns_created_instead_of_name_error(self):
        api = _FakeApi(existing=None)
        provider = GuangyaWebDAVProvider(api, client=SimpleNamespace())
        response = provider._handle_put(self.make_request(), "/media/demo.mkv")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(api.upload_calls[0][2], "demo.mkv")

    def test_put_existing_file_returns_no_content(self):
        api = _FakeApi(existing=SimpleNamespace(path="/media/demo.mkv", type="file"))
        provider = GuangyaWebDAVProvider(api, client=SimpleNamespace())
        response = provider._handle_put(self.make_request(), "/media/demo.mkv")
        self.assertEqual(response.status_code, 204)


if __name__ == "__main__":
    unittest.main(verbosity=2)
