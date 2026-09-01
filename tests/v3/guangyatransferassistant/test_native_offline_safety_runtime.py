"""脱离 MoviePilot 运行时验证 v1.8.0 安全层的真实方法行为。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[3]
SAFETY = ROOT / "plugins.v3" / "guangyatransferassistant" / "offline_safety_v180.py"
text = SAFETY.read_text(encoding="utf-8")
tree = ast.parse(text)

# 只抽取安全 mixin 类，移除相对 import，给最小状态常量即可。
class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GuangYaOfflineSafetyMixin")
module = ast.Module(body=[class_node], type_ignores=[])
ast.fix_missing_locations(module)
ns: Dict[str, Any] = {
    "Any": Any,
    "Dict": Dict,
    "SOURCE_INFLIGHT_STATES": {"dispatching", "submitted", "queued", "waiting"},
}
exec(compile(module, str(SAFETY), "exec"), ns)
Mixin = ns["GuangYaOfflineSafetyMixin"]


class _Base:
    def _submit_offline_source(self, source_id: str):
        self.base_submit_calls += 1
        return {"success": True, "message": "base-submit"}

    def _poll_offline_source(self, source):
        return self.poll_result


class _Harness(Mixin, _Base):
    def __init__(self, source):
        self.source = dict(source)
        self.base_submit_calls = 0
        self.poll_calls = 0
        self.retry_calls = 0
        self.poll_result = {"success": True, "data": dict(source)}

    def _source_store(self):
        return {"items": {str(self.source.get("id")): dict(self.source)}}

    def _poll_offline_source(self, source):
        self.poll_calls += 1
        return super()._poll_offline_source(source)

    def _retry_offline_task(self, source):
        self.retry_calls += 1
        return {"success": True, "message": "retry", "data": dict(source)}

    def _update_source(self, source_id, **fields):
        self.source.update(fields)
        return dict(self.source)


def test_existing_queued_task_only_polls_and_never_calls_base_submit():
    source = {"id": "s1", "task_id": "task-1", "state": "queued", "attempts": 1}
    harness = _Harness(source)
    result = Mixin._submit_offline_source(harness, "s1")
    assert result["success"] is True
    assert harness.poll_calls == 1
    assert harness.base_submit_calls == 0
    assert harness.retry_calls == 0


def test_existing_retry_task_uses_native_retry_not_new_submit():
    source = {"id": "s1", "task_id": "task-1", "state": "retry", "attempts": 1}
    harness = _Harness(source)
    result = Mixin._submit_offline_source(harness, "s1")
    assert result["success"] is True
    assert harness.retry_calls == 1
    assert harness.base_submit_calls == 0


def test_poll_transport_failure_restores_waiting_and_attempt_count():
    source = {"id": "s1", "task_id": "task-1", "state": "waiting", "attempts": 3, "task_status": 1}
    harness = _Harness(source)
    harness.poll_result = {
        "success": False,
        "message": "temporary network failure",
        "data": {**source, "state": "failed", "attempts": 3, "task_status": 1},
    }
    result = Mixin._poll_offline_source(harness, source)
    assert result["success"] is False
    assert result["data"]["state"] == "waiting"
    assert result["data"]["attempts"] == 3
    assert harness.source["state"] == "waiting"


def test_explicit_guangya_status_5_is_not_masked_as_network_failure():
    source = {"id": "s1", "task_id": "task-1", "state": "waiting", "attempts": 3, "task_status": 1}
    harness = _Harness(source)
    harness.poll_result = {
        "success": False,
        "message": "native task failed",
        "data": {**source, "state": "failed", "task_status": 5},
    }
    result = Mixin._poll_offline_source(harness, source)
    assert result["data"]["state"] == "failed"
    assert result["data"]["task_status"] == 5


def test_public_view_removes_raw_magnet_tracker_parameters():
    source = {
        "id": "s1",
        "type": "magnet",
        "identity": "0123456789abcdef0123456789abcdef01234567",
        "uri": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&tr=https://tracker.example/private-passkey",
    }
    public = Mixin._source_public_view(source)
    assert "uri" not in public
    assert "private-passkey" not in public["uri_preview"]
    assert public["uri_preview"] == "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
