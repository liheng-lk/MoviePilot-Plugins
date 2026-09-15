"""r108 corrected GuangYa direct-share access protocol regressions."""
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
    pkg = "_guangya_r108_contract"
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
        return {
            "success": True,
            "share_id": _share_identity(share_url).split("|", 1)[0],
            "file_count": 0,
            "leaf_count": 0,
            "files": [],
        }


class _ClientFullOpaqueWorks:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        if "get_share_access_token" in url:
            assert data == {"shareId": "ABC_suffix", "code": "ab12"}
            return {"code": 0, "msg": "success", "data": {"accessToken": "tok-full"}}
        if "get_share_page_files_list" in url:
            assert data["accessToken"] == "tok-full"
            assert "shareId" not in data
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
                    "data": {"list": [{
                        "fileId": "file1",
                        "fileName": "Demo.S01E01.1080p.mkv",
                        "type": 1,
                        "fileSize": 123456,
                    }]},
                }
        raise AssertionError((url, data))


class _ClientPageZeroFallback:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        if "get_share_access_token" in url:
            assert data["shareId"] == "ABC_suffix"
            return {"code": 0, "msg": "success", "data": {"accessToken": "tok-full"}}
        if "get_share_page_files_list" in url:
            assert "shareId" not in data
            if data["page"] == 1:
                return {"code": 0, "msg": "success", "data": {"list": []}}
            if data["page"] == 0:
                return {"code": 0, "msg": "success", "data": {"list": [{
                    "fileId": "file2",
                    "fileName": "Demo.S01E02.2160p.mp4",
                    "type": 1,
                    "fileSize": 222,
                }]}}
        raise AssertionError((url, data))


class _ClientFullShareListCompat:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        if "get_share_access_token" in url:
            assert data["shareId"] == "ABC_suffix"
            return {"code": 0, "msg": "success", "data": {"accessToken": "tok-full"}}
        if "get_share_page_files_list" in url:
            assert data["accessToken"] == "tok-full"
            if "shareId" not in data:
                return {"code": 400, "msg": "shareId required by legacy endpoint"}
            assert data["shareId"] == "ABC_suffix"
            return {"code": 0, "msg": "success", "data": {"list": [{
                "fileId": "file3",
                "fileName": "Demo.S01E03.mkv",
                "type": 1,
                "fileSize": 333,
            }]}}
        raise AssertionError((url, data))


class _ClientAccessFails:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.calls = []

    def _request(self, method="POST", url="", data=None, need_auth=False):
        data = dict(data or {})
        self.calls.append((url, data, need_auth))
        if "get_share_access_token" in url:
            assert data["shareId"] == "ABC_suffix"
            return {"code": 403, "msg": "invalid share or code"}
        raise AssertionError("list endpoint must not be called without access token")


def _probe(client):
    module = _resource_module()
    mixin = module.GuangYaShareLeafCompatV11225Mixin

    class Probe(mixin, _BaseProbe):
        pass

    return Probe(client)


def test_full_composite_share_id_is_opaque_and_token_only_list_is_primary():
    client = _ClientFullOpaqueWorks()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=ab12")
    assert result["success"] is True
    assert result["share_id"] == "ABC_suffix"
    assert result["access_share_id_v216"] == "ABC_suffix"
    assert result["share_access_attempts_v216"] == ["ABC_suffix"]
    assert result["share_list_protocol_r108"] == "token_page1"
    assert result["file_count"] == 2
    assert result["leaf_count"] == 1
    assert result["files"][0]["relative_path"] == "Demo/Demo.S01E01.1080p.mkv"
    access = [call for call in client.calls if "get_share_access_token" in call[0]]
    listing = [call for call in client.calls if "get_share_page_files_list" in call[0]]
    assert access[0][1] == {"shareId": "ABC_suffix", "code": "ab12"}
    assert all("shareId" not in call[1] for call in listing)
    assert all(call[2] is False for call in access + listing)


def test_token_only_page1_empty_can_retry_page0_without_changing_share_identity():
    client = _ClientPageZeroFallback()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=ab12")
    assert result["success"] is True
    assert result["access_share_id_v216"] == "ABC_suffix"
    assert result["share_access_attempts_v216"] == ["ABC_suffix"]
    assert result["share_list_protocol_r108"] == "token_page0"
    assert result["files"][0]["relative_path"] == "Demo.S01E02.2160p.mp4"


def test_list_compat_retry_may_add_only_the_full_share_id_never_a_numeric_prefix():
    client = _ClientFullShareListCompat()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=ab12")
    assert result["success"] is True
    assert result["share_list_protocol_r108"] == "token_fullshare_page1"
    compat = [call for call in client.calls if "get_share_page_files_list" in call[0] and "shareId" in call[1]]
    assert compat
    assert {call[1]["shareId"] for call in compat} == {"ABC_suffix"}


def test_unconfirmed_share_access_failure_stays_retryable_and_never_truncates_id():
    client = _ClientAccessFails()
    probe = _probe(client)
    result = probe._inspect_share("https://www.guangyapan.com/s/ABC_suffix?code=wrong")
    assert result["success"] is False
    assert result["retryable"] is True
    assert result["reason"] == "legacy_empty_result"
    assert result["stage"] == "list_share_files"
    assert result["share_access_attempts_v216"] == ["ABC_suffix"]
    assert "分享读取失败" in result["message"]


def test_r108_share_access_contract_survives_later_release():
    share = _bundled("share_leaf_compat_v11225")
    assert 'full_share_id.split("_", 1)[0]' not in share
    assert 'data={"shareId": full_share_id, "code": code}' in share
    assert '("token_page1", 1, False)' in share
    assert '("token_fullshare_page1", 1, True)' in share
    assert '"access_share_id_v216": full_share_id' in share
