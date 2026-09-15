"""r106 direct GuangYa restore_share payload regressions."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List


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


def _restore_method():
    tree = ast.parse(_bundled("legacy"), filename="<legacy>")
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaTransferAssistant"
    )
    fn = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_restore_items"
    )
    ns = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Path": Path,
        "_normalize_config_path": lambda value, default="/": str(value or default),
        "_safe_relative_path": lambda value: str(value or "").strip("/"),
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<restore_items>", "exec"), ns)
    return ns["_restore_items"]


class _Client:
    API_BASE_URL = "https://api.guangyapan.test"

    def __init__(self):
        self.payloads = []

    def _request(self, method="POST", url="", data=None, need_auth=True):
        assert "restore_share" in url
        self.payloads.append(dict(data or {}))
        return {"code": 0, "msg": "success", "data": {}}


class _Api:
    def get_folder(self, _path):
        return SimpleNamespace(fileid="dest-parent")


class _Probe:
    def __init__(self):
        self.client = _Client()
        self.api = _Api()
        self.states = []
        self.logs = []

    def _get_guangya_runtime(self):
        return self.client, self.api

    def _set_job_state(self, *args, **kwargs):
        self.states.append((args, kwargs))

    def _plugin_log(self, *args):
        self.logs.append(args)

    @staticmethod
    def _is_success(response):
        return isinstance(response, dict) and response.get("code") in (0, "0")

    def _verify_restored_group(self, api, parent_id, parent_path, items, max_try=30, interval=1.0):
        assert api is self.api
        assert parent_id == "dest-parent"
        return {"success": True, "verified_items": list(items)}


def _item():
    return {
        "id": "file-1",
        "name": "Demo.S01E01.mkv",
        "relative_path": "Demo.S01E01.mkv",
        "effective_path": "Demo.S01E01.mkv",
        "target_parent": "",
        "size": 123,
    }


def test_restore_share_uses_same_base_share_id_as_access_token():
    method = _restore_method()
    probe = _Probe()
    result = method(
        probe,
        {
            "access_token": "tok-base",
            "share_id": "ABC_suffix",
            "access_share_id_v216": "ABC",
            "share_id_request_v11225": "ABC",
        },
        "/target",
        [_item()],
        job_key="job-1",
    )
    assert result["success"] is True
    assert len(probe.client.payloads) == 1
    payload = probe.client.payloads[0]
    assert payload["accessToken"] == "tok-base"
    assert payload["shareId"] == "ABC"
    assert payload["fileIds"] == ["file-1"]
    assert payload["parentId"] == "dest-parent"


def test_restore_share_uses_share_id_request_for_old_v11225_probe_shape():
    method = _restore_method()
    probe = _Probe()
    result = method(
        probe,
        {
            "access_token": "tok-old",
            "share_id": "ABC_suffix",
            "share_id_request_v11225": "ABC",
        },
        "/target",
        [_item()],
        job_key="job-2",
    )
    assert result["success"] is True
    assert probe.client.payloads[0]["shareId"] == "ABC"


def test_restore_share_legacy_probe_still_uses_original_share_id():
    method = _restore_method()
    probe = _Probe()
    result = method(
        probe,
        {
            "access_token": "tok-full",
            "share_id": "FULL_ONLY",
        },
        "/target",
        [_item()],
        job_key="job-3",
    )
    assert result["success"] is True
    assert probe.client.payloads[0]["shareId"] == "FULL_ONLY"


def test_missing_access_token_fails_before_restore_request():
    method = _restore_method()
    probe = _Probe()
    result = method(
        probe,
        {
            "share_id": "ABC_suffix",
            "access_share_id_v216": "ABC",
        },
        "/target",
        [_item()],
        job_key="job-4",
    )
    assert result["success"] is False
    assert result["retryable"] is True
    assert result["stage"] == "restore_share"
    assert result["reason"] == "missing_access_token"
    assert probe.client.payloads == []


def test_r106_restore_pairing_contract_survives_later_release():
    legacy = _bundled("legacy")
    assert 'probe.get("access_share_id_v216")' in legacy
    assert 'probe.get("share_id_request_v11225")' in legacy
    assert '"reason": "missing_access_token"' in legacy
