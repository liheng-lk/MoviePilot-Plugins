from __future__ import annotations

import ast
import threading
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[3]
MULTI = ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py"
SOURCE = MULTI.read_text(encoding="utf-8")


def _mixin_class():
    tree = ast.parse(SOURCE, filename=str(MULTI))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaMultiSourceMixin")
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Path": Path,
        "threading": threading,
        "time": __import__("time"),
        "SOURCE_PENDING_STATES": {"new", "retry"},
        "SOURCE_INFLIGHT_STATES": {"dispatching", "submitted", "queued", "waiting"},
        "normalize_source_uri": lambda uri: {"type": "magnet", "uri": uri, "identity": "x", "name": "", "size": 0},
        "_is_video": lambda _name: False,
        "_is_subtitle": lambda _name: False,
        "_episode_numbers": lambda _name: (0, []),
        "_normalize_media_text": lambda value: str(value or "").strip().lower(),
        "GuangYaSourceStoreMixin": type("Base", (), {}),
    }
    exec(compile(module, str(MULTI), "exec"), ns)
    return ns["GuangYaMultiSourceMixin"]


def test_spawn_dispatch_reports_busy_state_instead_of_silent_success():
    mixin = _mixin_class()

    class Harness(mixin):
        _enabled = True

        def _claim_source_dispatch_slot(self, _source_id: str) -> bool:
            return False

    result = Harness()._spawn_source_dispatch("src-1")
    assert result["success"] is False
    assert result["reason"] == "already_running"


def test_api_source_dispatch_returns_dispatch_result_when_busy():
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self.items = {"src-1": {"id": "src-1"}}

        def _source_store(self):
            return {"items": self.items}

        def _spawn_source_dispatch(self, _source_id: str):
            return {"success": False, "message": "来源正在处理中，请稍后重试", "reason": "already_running"}

    result = Harness().api_source_dispatch("src-1")
    assert result["success"] is False
    assert result["reason"] == "already_running"


def test_api_source_retry_rejects_manual_retry_for_inflight_source():
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self.items = {"src-1": {"id": "src-1", "state": "waiting"}}

        def _source_store(self):
            return {"items": self.items}

        def _update_source(self, source_id: str, **fields):
            self.items[source_id].update(fields)
            return dict(self.items[source_id])

    result = Harness().api_source_retry("src-1")
    assert result["success"] is False
    assert result["reason"] == "already_inflight"


def test_api_source_retry_rolls_back_state_when_dispatch_not_accepted():
    mixin = _mixin_class()

    class Harness(mixin):
        def __init__(self):
            self.items = {
                "src-1": {"id": "src-1", "state": "failed", "next_retry_at": 123, "last_error": "boom"},
            }

        def _source_store(self):
            return {"items": self.items}

        def _update_source(self, source_id: str, **fields):
            self.items[source_id].update(fields)
            return dict(self.items[source_id])

        def _spawn_source_dispatch(self, _source_id: str):
            return {"success": False, "message": "来源正在处理中，请稍后重试", "reason": "already_running"}

    harness = Harness()
    result = harness.api_source_retry("src-1")
    assert result["success"] is False
    assert harness.items["src-1"]["state"] == "failed"
    assert harness.items["src-1"]["next_retry_at"] == 123
    assert harness.items["src-1"]["last_error"] == "boom"


def test_api_source_add_reports_dispatch_result_without_faking_queue_success():
    mixin = _mixin_class()

    class Harness(mixin):
        def _upsert_source(self, *_args, **_kwargs):
            return {"id": "src-1"}

        def _spawn_source_dispatch(self, _source_id: str):
            return {"success": False, "message": "插件未启用，无法调度来源", "reason": "plugin_disabled"}

    result = Harness().api_source_add(1, "magnet:?xt=urn:btih:abc", dispatch=True)
    assert result["success"] is True
    assert result["dispatch"]["success"] is False
    assert "暂未进入后台队列" in result["message"]
