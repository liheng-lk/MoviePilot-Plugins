"""Unified transfer routing and MP-priority naming contracts."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
ENTRY_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
ENTRY = ENTRY_PATH.read_text(encoding="utf-8")

_REQUIRED_FUNCTIONS = {
    "_normalize_unified_resource_candidate",
    "_unified_transfer_route_name",
    "_extract_transfer_technical_tags",
    "_format_mp_transfer_name",
    "_select_verified_new_landing",
}
_REQUIRED_CONSTANTS = {
    "_UNIFIED_TRANSFER_ROUTES",
    "_UNIFIED_SOURCE_PRIORITY",
}


def _load_helpers():
    tree = ast.parse(ENTRY, filename=str(ENTRY_PATH))
    body = []
    found_functions = set()
    found_constants = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _REQUIRED_FUNCTIONS:
            body.append(node)
            found_functions.add(node.name)
            continue
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets
                if isinstance(target, ast.Name)
            }
            if names.intersection(_REQUIRED_CONSTANTS):
                body.append(node)
                found_constants.update(names.intersection(_REQUIRED_CONSTANTS))
    assert found_functions == _REQUIRED_FUNCTIONS
    assert found_constants == _REQUIRED_CONSTANTS
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re}
    exec(compile(module, str(ENTRY_PATH), "exec"), namespace)
    return namespace


def test_four_resource_types_use_one_execution_contract():
    ns = _load_helpers()
    normalize = ns["_normalize_unified_resource_candidate"]
    route = ns["_unified_transfer_route_name"]

    cases = [
        (
            {"url": "https://pan.xunlei.com/s/VP-demo?pwd=abcd"},
            "xunlei",
            "xunlei_json_flash",
            0,
        ),
        (
            {"share_url": "https://www.guangyapan.com/s/demo?code=1234"},
            "guangya",
            "guangya_share_restore",
            1,
        ),
        (
            {"uri": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"},
            "magnet",
            "cloudcollection",
            2,
        ),
        (
            {"uri": "ed2k://|file|Demo.S01E01.mkv|123456|0123456789abcdef0123456789abcdef|/"},
            "ed2k",
            "cloudcollection",
            3,
        ),
    ]

    for raw, expected_type, expected_route, expected_priority in cases:
        for origin in ("telegram", "gying"):
            row = normalize(raw, origin=origin)
            assert row["type"] == expected_type
            assert row["route"] == expected_route
            assert row["priority"] == expected_priority
            assert row["origin"] == origin
            assert route(expected_type) == expected_route


def test_unknown_pan_link_is_not_misrouted():
    ns = _load_helpers()
    normalize = ns["_normalize_unified_resource_candidate"]
    row = normalize({"url": "https://115.com/s/not-guangya"}, origin="gying")
    assert row["type"] == ""
    assert row["route"] == ""
    assert row["priority"] == 99


def test_mp_priority_tv_name_preserves_technical_tags():
    ns = _load_helpers()
    format_name = ns["_format_mp_transfer_name"]
    result = format_name(
        "幸运女神",
        2026,
        "幸运女神 S01E07.mkv",
        "Some.Show.2026.S01E07.2160p.WEB-DL.H265.DDP5.1.HDR10-GROUP.mkv",
        False,
    )
    assert result == "幸运女神 - S01E07 - 2160p WEB-DL H265 DDP5.1 HDR10 GROUP.mkv"


def test_mp_priority_movie_name_uses_mp_year_and_preserves_tags():
    ns = _load_helpers()
    format_name = ns["_format_mp_transfer_name"]
    result = format_name(
        "沙丘2",
        2024,
        "沙丘2.mkv",
        "Dune.Part.Two.2024.2160p.BluRay.REMUX.DV.HEVC.TrueHD.7.1-GROUP.mkv",
        True,
    )
    assert result == "沙丘2 (2024) - 2160p BluRay REMUX DV HEVC TrueHD 7.1 GROUP.mkv"


def test_name_without_technical_tags_stays_clean():
    ns = _load_helpers()
    format_name = ns["_format_mp_transfer_name"]
    result = format_name(
        "示例剧",
        2026,
        "示例剧 S01E02.mkv",
        "Example.Show.S01E02.mkv",
        False,
    )
    assert result == "示例剧 - S01E02.mkv"


def test_new_landing_requires_fresh_file_id_name_and_size():
    ns = _load_helpers()
    verify = ns["_select_verified_new_landing"]
    rows = [
        {"file_id": "old-1", "name": "示例剧 - S01E02 - 2160p WEB-DL H265.mkv", "size": 1000},
        {"file_id": "new-2", "name": "示例剧 - S01E02 - 2160p WEB-DL H265.mkv", "size": 1000},
    ]
    receipt = verify(
        {"old-1"},
        rows,
        "示例剧 - S01E02 - 2160p WEB-DL H265.mkv",
        1000,
    )
    assert receipt["verified"] is True
    assert receipt["file_id"] == "new-2"
    assert receipt["reason"] == "new_file_confirmed"


def test_preexisting_or_wrong_size_never_counts_as_current_landing():
    ns = _load_helpers()
    verify = ns["_select_verified_new_landing"]
    existing = verify(
        {"same-id"},
        [{"file_id": "same-id", "name": "示例剧 - S01E02.mkv", "size": 1000}],
        "示例剧 - S01E02.mkv",
        1000,
    )
    assert existing == {"verified": False, "reason": "preexisting_only"}

    wrong_size = verify(
        set(),
        [{"file_id": "new-id", "name": "示例剧 - S01E02.mkv", "size": 999}],
        "示例剧 - S01E02.mkv",
        1000,
    )
    assert wrong_size == {"verified": False, "reason": "expected_file_not_found"}


def test_cloudcollection_source_contains_real_target_readback_contract():
    source = (
        ROOT / "plugins.v3" / "guangyatransferassistant" / "multisource_v180.py"
    ).read_text(encoding="utf-8")
    assert "def _verify_offline_target_landing(" in source
    assert "pre_landing_file_ids" in source
    assert "target_parent_id" in source
    assert "target_directory_readback" in source
    assert '"preexisting_only"' in source


def test_xunlei_runtime_requires_verified_landing_before_success():
    text = ENTRY
    marker = "class GuangYaTransferAssistant("
    start = text.rindex(marker)
    final_class = text[start:]
    assert "def _rapid_transfer_xunlei_file(" in final_class
    assert "_select_verified_new_landing(" in final_class
    assert '"landing_verified": True' in final_class
    assert '"pending_verification": True' in final_class
    assert "def _dispatch_xunlei_flash(" in final_class
    assert "_xunlei_pending_landing_v200" in final_class
    assert 'result["handled"] = True' in final_class


def test_xunlei_success_state_and_notification_require_verified_landing():
    plugin = ROOT / "plugins.v3" / "guangyatransferassistant"
    flash = (plugin / "xunlei_flash_v193.py").read_text(encoding="utf-8")
    runtime = (plugin / "runtime_fix_v1113.py").read_text(encoding="utf-8")

    assert '"landing_verified": bool(result.get("landing_verified"))' in flash
    assert '"final_name": str(result.get("final_name") or "")' in flash
    notify = runtime.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    def _notify_cloud_completed_v1113(", 1
    )[0]
    assert 'and bool(row.get("landing_verified"))' in notify
    assert 'row.get("final_name")' in notify
    assert "最终文件：" in notify
    assert "key not in before_completed" in notify


def test_gying_observability_distinguishes_cache_from_real_network():
    plugin = ROOT / "plugins.v3" / "guangyatransferassistant"
    protocol = (plugin / "gying_protocol_v1106.py").read_text(encoding="utf-8")
    observability = (plugin / "gying_observability_v1104.py").read_text(encoding="utf-8")
    assert '"transport": "cache"' in protocol
    assert '"cache_hit": True' in protocol
    assert '"search_http_requests": 0' in protocol
    assert '"transport": "network"' in protocol
    assert "downurl_attempts" in protocol
    assert "downurl_success" in protocol
    assert "downurl_failures" in protocol
    assert '"transport", "cache_hit", "cache_age_seconds", "search_http_requests"' in observability


def test_final_plugin_runtime_uses_unified_matrix_and_mp_naming():
    import sys

    here = Path(__file__).resolve().parent if "__file__" in globals() else ROOT / "tests" / "v3" / "guangyatransferassistant"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from final_plugin_harness_v211 import make_final_plugin

    plugin = make_final_plugin()
    resources = [
        ({"url": "https://pan.xunlei.com/s/demo?pwd=1234"}, "xunlei", "xunlei_json_flash"),
        ({"share_url": "https://www.guangyapan.com/share/demo"}, "guangya", "guangya_share_restore"),
        ({"uri": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"}, "magnet", "cloudcollection"),
        ({"uri": "ed2k://|file|Demo.mkv|123|0123456789abcdef0123456789abcdef|/"}, "ed2k", "cloudcollection"),
    ]
    for origin in ("telegram", "gying"):
        for raw, expected_type, expected_route in resources:
            row = plugin._normalize_transfer_candidate(raw, origin=origin)
            assert row["type"] == expected_type
            assert row["route"] == expected_route
            assert row["origin"] == origin

    subscribe = SimpleNamespace(name="幸运女神", year=2026, season=1, type="TV")
    result = plugin._canonical_transfer_name_v11226(
        subscribe,
        "Some.Show.2026.S01E07.2160p.WEB-DL.H265.DDP5.1.HDR10-GROUP.mkv",
    )
    assert result == "幸运女神 - S01E07 - 2160p WEB-DL H265 DDP5.1 HDR10 GROUP.mkv"


def test_cloud_success_notification_requires_verified_video_and_final_name():
    plugin = ROOT / "plugins.v3" / "guangyatransferassistant"
    runtime = (plugin / "runtime_fix_v1113.py").read_text(encoding="utf-8")
    notify = runtime.split("    def _notify_cloud_completed_v1113(", 1)[1].split(
        "    def _notify_cloud_failed_v1119(", 1
    )[0]
    assert 'if not bool(current.get("remote_video_confirmed")):' in notify
    assert 'current.get("landing_file_name")' in notify
    assert '"☁️ 光鸭云添加完成"' in notify
    assert "云添加任务完成" not in notify
    assert 'current.get("completion_notified_at")' in notify
    assert "completion_notified_at=self._now_text()" in notify


def test_cloudcollection_final_name_is_confirmed_before_completed_state():
    plugin = ROOT / "plugins.v3" / "guangyatransferassistant"
    source = (plugin / "multisource_v180.py").read_text(encoding="utf-8")
    assert "def _finalize_offline_remote_name_v200(" in source
    poll = source.split("    def _poll_offline_source(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 调度与 API", 1
    )[0]
    assert "_finalize_offline_remote_name_v200(" in poll
    assert 'verify_source = "final_name_confirmed"' in poll
    assert 'verify_source = "final_name_pending"' in poll
    assert poll.index("_finalize_offline_remote_name_v200(") < poll.index(
        'completed_state = "completed" if verified else "waiting"'
    )


def test_guangya_share_waits_for_final_rename_before_success():
    plugin = ROOT / "plugins.v3" / "guangyatransferassistant"
    source = (plugin / "channel_title_rename_v11226.py").read_text(encoding="utf-8")
    rename = source.split("    def _rename_restored_media_v11224(", 1)[1].split(
        "    def _restore_items(", 1
    )[0]
    restore = source.split("    def _restore_items(", 1)[1].split(
        "\n\n__all__", 1
    )[0]
    assert 'item["rename_verified_v200"] = True' in rename
    assert 'item["final_name_v200"] = desired' in rename
    assert 'result["pending_verification"] = True' in restore
    assert 'result["success"] = False' in restore
    assert '"RENAME_VERIFY_PENDING"' in restore
    assert 'result["final_names"] = final_names' in restore


def test_telegram_real_parser_produces_all_four_resource_types():
    import importlib
    import sys

    here = Path(__file__).resolve().parent if "__file__" in globals() else ROOT / "tests" / "v3" / "guangyatransferassistant"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from final_plugin_harness_v211 import make_final_plugin

    plugin = make_final_plugin()
    legacy = importlib.import_module("plugins.v3.guangyatransferassistant.legacy")
    page = """
    <div class="tgme_widget_message" data-post="demo/100">
      <div class="tgme_widget_message_text">
        名称：示例剧 (2026)
        S01E01
        https://www.guangyapan.com/s/GYDEMO?code=1234
        https://pan.xunlei.com/s/XLDEMO?pwd=abcd
        magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Demo.S01E01
        ed2k://|file|Demo.S01E01.1080p.WEB-DL.mkv|123456|0123456789abcdef0123456789abcdef|/
      </div>
    </div>
    """
    entries = legacy._extract_channel_entries(
        page,
        "https://tgm.li668.asia/demo",
        "TG-DEMO",
    )
    assert entries
    entry = entries[0]
    candidates = []
    if entry.get("share_url"):
        candidates.append({"share_url": entry["share_url"]})
    candidates.extend(entry.get("xunlei_sources") or [])
    candidates.extend(entry.get("external_sources") or [])
    normalized = [
        plugin._normalize_transfer_candidate(row, origin="telegram")
        for row in candidates
    ]
    types = {row["type"] for row in normalized if row.get("type")}
    assert types == {"xunlei", "guangya", "magnet", "ed2k"}
    assert entry.get("candidate_types") == ["xunlei", "guangya", "magnet", "ed2k"]


def test_gying_real_protocol_payload_produces_all_four_resource_types():
    import importlib
    import sys

    here = Path(__file__).resolve().parent if "__file__" in globals() else ROOT / "tests" / "v3" / "guangyatransferassistant"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from final_plugin_harness_v211 import make_final_plugin

    plugin = make_final_plugin()
    protocol = importlib.import_module(
        "plugins.v3.guangyatransferassistant.gying_protocol_v1106"
    )
    payload = {
        "data": {
            "panlist": {
                "url": [
                    "https://www.guangyapan.com/s/GYDEMO?code=1234",
                    "https://pan.xunlei.com/s/XLDEMO?pwd=abcd",
                ],
                "name": ["示例剧 S01E01", "示例剧 S01E01"],
                "type": ["guangya", "xunlei"],
                "p": ["1234", "abcd"],
                "id": ["gy-1", "xl-1"],
            },
            "downlist": {
                "list": {
                    "t": ["示例剧 S01E01"],
                    "m": ["0123456789abcdef0123456789abcdef01234567"],
                    "k": [0],
                    "u": ["bt-1"],
                    "s": ["1.2GB"],
                    "e": [10],
                    "p": ["GYING"],
                    "n": [1],
                }
            },
            "raw": (
                "ed2k://|file|Demo.S01E01.1080p.WEB-DL.mkv|123456|"
                "0123456789abcdef0123456789abcdef|/"
            ),
        }
    }
    rows = protocol.extract_resource_rows_v1106(
        payload,
        {"title": "示例剧", "year": 2026, "type": "tv", "id": "100"},
    )
    normalized = [
        plugin._normalize_transfer_candidate(row, origin="gying")
        for row in rows
    ]
    types = {row["type"] for row in normalized if row.get("type")}
    assert types == {"xunlei", "guangya", "magnet", "ed2k"}
    ordered = sorted(normalized, key=lambda row: row.get("priority", 99))
    assert [row["type"] for row in ordered[:4]] == [
        "xunlei",
        "guangya",
        "magnet",
        "ed2k",
    ]
