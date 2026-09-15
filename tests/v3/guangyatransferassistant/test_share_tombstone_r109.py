"""r109 GuangYa share tombstone / retry semantics."""
from __future__ import annotations

import ast
from pathlib import Path


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


def _diag_module():
    ns = {}
    exec(compile(_bundled("transfer_diag_v209"), "<transfer_diag_v209>", "exec"), ns)
    return ns


def test_ambiguous_invalid_share_or_code_is_not_long_expired():
    ns = _diag_module()
    classify = ns["classify_share_inspect_failure"]
    for message in (
        "invalid share or code",
        "分享链接错误",
        "提取码错误",
        "HTTP 404",
    ):
        row = classify(message, source="guangya")
        assert row["state"] == "FAILED_RETRYABLE"
        assert row["reason_code"] != "SHARE_EXPIRED"


def test_explicit_deleted_or_expired_share_still_gets_expired_reason():
    ns = _diag_module()
    classify = ns["classify_share_inspect_failure"]
    for message in (
        "分享不存在",
        "分享已失效",
        "分享已过期",
        "resource deleted",
        "not found",
    ):
        assert classify(message, source="guangya")["reason_code"] == "SHARE_EXPIRED"


def test_temporary_tombstone_is_short_and_status_keeps_temporary_truth():
    production = _bundled("production_safety_v208")
    assert "_tombstone_expired_ttl_v208 = 12 * 3600" in production
    assert "_tombstone_temp_ttl_v208 = 90" in production
    assert "def _share_tombstone_status_v109" in production
    assert 'row["remaining_seconds"]' in production
    assert 'return bool(self._share_tombstone_status_v109(source_type, identity))' in production


def test_direct_route_force_bypasses_tombstone_and_temp_is_not_share_expired():
    legacy = _bundled("legacy")
    start = legacy.index('tombstone_status = getattr(self, "_share_tombstone_status_v109", None)')
    end = legacy.index("            probe = self._inspect_share(share_url)", start)
    block = legacy[start:end]
    assert "and not force" in block
    assert 'tombstone_reason_code = "API_ERROR" if temporary_tombstone else "SHARE_EXPIRED"' in block
    assert '"temporary": temporary_tombstone' in block
    assert "【资源退避r109】" in block


def test_auth_failure_does_not_poison_share_specific_tombstone():
    legacy = _bundled("legacy")
    start = legacy.index('marker = getattr(self, "_mark_share_tombstone_v208", None)')
    end = legacy.index("                continue", start) + len("                continue")
    block = legacy[start:end]
    assert 'inspect_code == "SHARE_EXPIRED"' in block
    assert '"HTTP_TIMEOUT", "NETWORK_ERROR", "MALFORMED_RESPONSE"' in block
    assert '"API_ERROR", "SHARE_INSPECT_FAILED"' in block
    assert "AUTH_ERROR" in block
    assert 'marker("guangya", share_id_only, error, temporary=False)' in block
    assert 'marker("guangya", share_id_only, error, temporary=True)' in block


def test_r109_tombstone_behavior_survives_later_release():
    final = ENTRY[ENTRY.rindex("\nclass GuangYaTransferAssistant("):]
    assert "_share_tombstone_status_v109" in _bundled("production_safety_v208")
    assert "_tombstone_temp_ttl_v208 = 90" in _bundled("production_safety_v208")
    assert "【资源退避r109】" in _bundled("legacy")
    assert "plugin_version" in final
