"""r105 GuangYa direct-share access protocol regressions."""
from __future__ import annotations

import ast
import hashlib
import re
import sys
import time
import types
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")


def _bundled(name: str) -> str:
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            return str(ast.literal_eval(node.value)[name])
    raise AssertionError("_BUNDLED_SOURCES missing")


def _safe_relative(value: Any) -> str:
    raw = str(value or "").replace("\\", "/")
    parts = []
    for part in raw.split("/"):
        token = part.strip()
        if not token or token in {".", ".."}:
            continue
        parts.append(token)
    return "/".join(parts)


def _share_identity(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    matched = re.search(r"/(?:s|share)/([A-Za-z0-9_-]+)", parsed.path or "", re.I)
    if not matched:
        return ""
    query = parse_qs(parsed.query)
    code = (
        query.get("code")
        or query.get("pwd")
        or query.get("passcode")
        or query.get("pass_code")
        or query.get("password")
        or [""]
    )[0]
    return f"{matched.group(1)}|{code}"


def _resource_module():
    pkg = "_guangya_r105_contract"
    package = types.ModuleType(pkg)
    package.__path__ = []
    sys.modules[pkg] = package

    legacy = types.ModuleType(f"{pkg}.legacy")
    legacy._extract_result_list = lambda response: [
        item for item in (
            ((response or {}).get("data") or {}).get("list") or []
            if isinstance((response or {}).get("data"), dict)
            else []
        )
        if isinstance(item, dict)
    ]
    legacy._is_subtitle = lambda path: str(path or "").lower().endswith((".srt", ".ass", ".ssa", ".vtt"))
    legacy._is_video = lambda path: str(path or "").lower().endswith((".mkv", ".mp4", ".ts", ".m2ts"))
    legacy._safe_relative_path = _safe_relative
    legacy._share_identity = _share_identity
    sys.modules[legacy.__name__] = legacy

    module = types.ModuleType(f"{pkg}.share_leaf_compat_v11225")
    module.__package__ = pkg
    sys.modules[module.__name__] = module
    exec(compile(_bundled("share_leaf_compat_v11225"), "<share_leaf_compat_v11225>", "exec"), module.__dict__)
    return module


class _BaseProbe:
    _max_share_files = 100
    _refresh_minutes = 5

    def __init__(self, client):
        self.client = client
        self._inspect_cache = {}
        self.logs = []

    @staticmethod
    def _is_success(response):
        if not isinstance(response, dict):
            return False
        return response.get("code") in (0, "0") or str(response.get("msg") or "").lower() == "success"

    def _get_guangya_runtime(self):
        return self.client, None

    def _plugin_log(self, *args):
        self.logs.append(args)

    def _inspect_share(self, share_url):
        # Reproduce the old false-success shape: endpoint returned code=0 but no nodes
        # because shareId was omitted from get_share_page_files_list.
        return {
            "success": True,
            "share_id": _share_identity(share_url).split("|", 1)[0],
            "file_count": 0,
            "leaf_count": 0,
            "files": [],
        }


class _BaseTokenFailure(_BaseProbe):
    pass


class _ClientBaseIdWorks:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        if "get_share_access_token" in url:
            assert data["code"] == "ab12"
            if data["shareId"] == "ABC":
                return {"code": 0, "msg": "success", "data": {"accessToken": "tok-base"}}
            return {"code": 404, "msg": "share not found"}
        if "get_share_page_files_list" in url:
            assert data["shareId"] == "ABC"
            assert data["accessToken"] == "tok-base"
            if not data["parentId"]:
                return {
                    "code": 0,
                    "msg": "success",
                    "data": {"list": [{"fileId": "dir1", "fileName": "Demo", "type": 2}]},
                }
            if data["parentId"] == "dir1":
                return {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "list": [{
                            "fileId": "file1",
                            "fileName": "Demo.S01E01.1080p.mkv",
                            "type": 1,
                            "fileSize": 123456,
                        }]
                    },
                }
        raise AssertionError((url, data))


class _ClientFullIdAfterBaseEmpty:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        share_id = data.get("shareId")
        if "get_share_access_token" in url:
            return {"code": 0, "msg": "success", "data": {"accessToken": f"tok-{share_id}"}}
        if "get_share_page_files_list" in url:
            assert data["accessToken"] == f"tok-{share_id}"
            if share_id == "ABC":
                return {"code": 0, "msg": "success", "data": {"list": []}}
            if share_id == "ABC_suffix":
                return {
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "list": [{
                            "fileId": "file2",
                            "fileName": "Demo.S01E02.2160p.mp4",
                            "type": 1,
                            "fileSize": 222,
                        }]
                    },
                }
        raise AssertionError((url, data))


class _ClientAccessFails:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        if "get_share_access_token" in url:
            return {"code": 403, "msg": "invalid share or code"}
        raise AssertionError("list endpoint must not be called without access token")


def _probe(client):
    module = _resource_module()
    mixin = module.GuangYaShareLeafCompatV11225Mixin

    class Probe(mixin, _BaseProbe):
        pass

    return Probe(client)


def test_legacy_success_empty_list_is_not_treated_as_confirmed_empty_share():
    client = _ClientBaseIdWorks()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=ab12")
    assert result["success"] is True
    assert result["share_id"] == "ABC_suffix"
    assert result["access_share_id_v216"] == "ABC"
    assert result["share_access_attempts_v216"] == ["ABC"]
    assert result["file_count"] == 2
    assert result["leaf_count"] == 1
    assert result["files"][0]["relative_path"] == "Demo/Demo.S01E01.1080p.mkv"
    assert result["files"][0]["size"] == 123456
    access = [call for call in client.calls if "get_share_access_token" in call[0]]
    listing = [call for call in client.calls if "get_share_page_files_list" in call[0]]
    assert access[0][1] == {"shareId": "ABC", "code": "ab12"}
    assert all(call[2] is False for call in access + listing)


def test_base_share_id_empty_result_falls_through_to_full_share_id_with_matching_token():
    client = _ClientFullIdAfterBaseEmpty()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=ab12")
    assert result["success"] is True
    assert result["access_share_id_v216"] == "ABC_suffix"
    assert result["share_access_attempts_v216"] == ["ABC", "ABC_suffix"]
    assert result["leaf_count"] == 1
    assert result["files"][0]["relative_path"] == "Demo.S01E02.2160p.mp4"


def test_unconfirmed_empty_share_fails_retryable_instead_of_becoming_no_media():
    client = _ClientAccessFails()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=wrong")
    assert result["success"] is False
    assert result["retryable"] is True
    assert result["reason"] == "legacy_empty_result"
    assert result["stage"] == "list_share_files"
    assert result["share_access_attempts_v216"] == ["ABC", "ABC_suffix"]
    assert "分享读取失败" in result["message"]


def test_release_marker_r105():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert 'plugin_version = "2.1.7"' in final
    assert 'build_id = "20260915-r105"' in final
