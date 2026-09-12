from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
DISPATCH = PLUGIN / "viewing_dispatch_v1113.py"
LOGGING = PLUGIN / "viewing_logging_v1113.py"
MULTI = PLUGIN / "multisource_v180.py"
PLUGIN_JSON = PLUGIN / "plugin.json"

entry_text = ENTRY.read_text(encoding="utf-8")
dispatch_text = DISPATCH.read_text(encoding="utf-8")
logging_text = LOGGING.read_text(encoding="utf-8")
multi_text = MULTI.read_text(encoding="utf-8")


def test_v1113_files_parse_and_release_is_published():
    for path, text in ((ENTRY, entry_text), (DISPATCH, dispatch_text), (LOGGING, logging_text)):
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "2.0.13"
    assert 'plugin_version = "2.0.13"' in entry_text
    assert "v1.12.5" in package["history"]
    assert "v1.12.3" in package["history"]
    assert "v1.10.13" in package["history"]


def test_v1113_mro_enables_logging_then_dispatch_before_old_gying_protocol():
    assert "from .viewing_logging_v1113 import GuangYaViewingLoggingV1113Mixin" in entry_text
    start = entry_text.index("class GuangYaTransferAssistant(")
    assert entry_text.index("GuangYaViewingLoggingV1113Mixin,", start) < entry_text.index(
        "GuangYaGyingProtocolV1106Mixin,", start
    )
    assert "class GuangYaViewingLoggingV1113Mixin(" in logging_text
    assert "GuangYaViewingDispatchV1113Mixin," in logging_text
    assert "GuangYaXunleiJsonPipelineV1117Mixin," in logging_text
    assert "GuangYaXunleiIntegrityV1116Mixin," in logging_text


def test_v1113_valid_btih_is_not_discarded_only_because_downlist_k_drifted():
    detail = dispatch_text.split("    def _gying_detail(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 远端命名", 1
    )[0]
    assert "_BTIH_V1113.fullmatch(btih)" in detail
    assert "kinds[index] = 0" in detail
    assert "Magnet字段兼容" in detail
    assert "后续交给光鸭原生云添加" in detail


def test_v1113_viewing_magnet_and_ed2k_are_bound_and_dispatched_to_native_cloudcollection():
    planner = dispatch_text.split("    def _dispatch_viewing_external_v1113(", 1)[1].split(
        "    def _try_transfer_subscription_inner(", 1
    )[0]
    assert "_gying_raw_results" in dispatch_text
    assert "normalize_source_uri" in dispatch_text
    assert 'source_type not in {"magnet", "ed2k"}' in dispatch_text
    assert "_provider_candidate_matches(subscribe, candidate)" in planner
    assert "self._upsert_source(" in planner
    assert 'origin="viewing_auto"' in planner
    assert "self._spawn_source_dispatch(source_id)" in planner
    assert "执行器=光鸭cloudcollection" in planner
    assert '"/cloudcollection/v1/create_task"' in multi_text
    assert "DownloadChain(" not in dispatch_text


def test_v1113_xunlei_is_flash_only_and_never_becomes_normal_download():
    xunlei_filter = dispatch_text.split("    def _viewing_external_candidates_v1113(", 1)[1].split(
        "    def _dispatch_viewing_external_v1113(", 1
    )[0]
    flash = dispatch_text.split("    def _rapid_transfer_xunlei_file(", 1)[1].split(
        "    def _dispatch_xunlei_flash(", 1
    )[0]
    assert 'if "pan.xunlei.com/s/" in lowered:' in xunlei_filter
    assert 'counts["xunlei"] += 1' in xunlei_filter
    assert "super()._rapid_transfer_xunlei_file" in flash
    assert "只尝试秒传，不做普通下载" in flash
    for forbidden in ("DownloadChain(", "downloadchain(", "oss2", "aria2", "qbittorrent"):
        assert forbidden.lower() not in dispatch_text.lower()


def test_v1113_name_keeps_original_and_appends_search_identity_before_extension():
    helper = dispatch_text.split("def _append_tag_to_name_v1113(", 1)[1].split(
        "\n\n\nclass GuangYaViewingDispatchV1113Mixin", 1
    )[0]
    resolve = dispatch_text.split("    def _resolve_offline_source(", 1)[1].split(
        "    @staticmethod\n    def _rename_result_ok_v1113", 1
    )[0]
    poll = dispatch_text.split("    def _poll_offline_source(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 迅雷", 1
    )[0]
    assert 'marker = f" [{extra}]"' in helper
    assert 'return f"{stem}{marker}{suffix}"[:limit]' in helper
    assert "source[\"label\"] = desired" in resolve
    assert "requested_name=desired" in resolve
    assert "client, _ = self._get_guangya_runtime()" in poll
    assert 'getattr(client, "rename", None)' in poll
    assert "/nd.bizuserres.s/v1/file/rename" in poll


def test_v1113_partial_success_does_not_hide_remaining_missing_episodes():
    method = logging_text.split("    def _try_transfer_subscription_inner(", 1)[1]
    gap = logging_text.split("    def _viewing_gap_v1113(", 1)[1].split(
        "    def _try_transfer_subscription_inner(", 1
    )[0]
    assert "missing - reserved - claimed" in gap
    assert "if bool(gap.get(\"covered\")):" in method
    assert "self._dispatch_viewing_external_v1113(subscribe)" in method
    assert "前序链未完整覆盖" in method


def test_v1113_full_logs_cover_search_flash_cloudadd_poll_naming_and_errors():
    combined = dispatch_text + "\n" + logging_text
    for marker in (
        "【观影执行】",
        "【迅雷秒传】",
        "【原生云添加】",
        "【命名】",
        "失败明细",
        "观影任务轮询结果",
        "规划结束",
    ):
        assert marker in combined


def test_v1113_xunlei_summary_log_does_not_warn_for_expected_no_share_fallback():
    dispatch = dispatch_text.split("    def _dispatch_xunlei_flash(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 观影 Magnet/ED2K -> 光鸭原生 cloudcollection", 1
    )[0]
    assert "expected_fallback" in dispatch
    assert 'int(result.get("shares") or 0) <= 0' in dispatch
    assert 'int(result.get("attempted_files") or 0) <= 0' in dispatch
    assert '"INFO" if bool(result.get("success")) or expected_fallback else "WARNING"' in dispatch




def _rename_confirm_probe():
    tree = ast.parse(dispatch_text, filename=str(DISPATCH))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GuangYaViewingDispatchV1113Mixin"
    )
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_confirm_remote_rename_v1113"
    )
    method.returns = None
    for arg in method.args.args:
        arg.annotation = None
    probe = ast.ClassDef(
        name="RenameConfirmProbe",
        bases=[],
        keywords=[],
        body=[method],
        decorator_list=[],
    )
    module = ast.Module(body=[probe], type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {
        "Any": Any,
        "Dict": Dict,
        "Path": Path,
        "time": time,
        "_norm_name_v1113": lambda value: re.sub(
            r"[^0-9a-z\u4e00-\u9fff]+",
            "",
            str(value or "").strip().lower(),
        ),
    }
    exec(compile(module, str(DISPATCH), "exec"), ns)
    return ns["RenameConfirmProbe"]


def test_remote_rename_confirmation_requires_readback_name_and_identity():
    Probe = _rename_confirm_probe()
    probe = Probe()

    class Api:
        def __init__(self):
            self.calls = 0

        def _find_item_in_parent(self, *, parent_path, name, expected_type):
            self.calls += 1
            assert parent_path == "/media/Demo (2026)"
            assert name == "Demo - S01E05 - 2160p.WEB-DL.mkv"
            assert expected_type == "file"
            if self.calls == 1:
                return None
            return SimpleNamespace(name=name, fileid="file-5")

        def _invalidate_path_cache(self, _path):
            return None

    result = probe._confirm_remote_rename_v1113(
        Api(),
        target_path="/media/Demo (2026)",
        desired_name="Demo - S01E05 - 2160p.WEB-DL.mkv",
        file_id="file-5",
        attempts=2,
        interval=0,
    )
    assert result["confirmed"] is True
    assert result["file_id"] == "file-5"
    assert result["attempts"] == 2


def test_remote_rename_confirmation_fails_closed_on_wrong_file_identity():
    Probe = _rename_confirm_probe()
    probe = Probe()

    class Api:
        @staticmethod
        def _find_item_in_parent(*, parent_path, name, expected_type):
            return SimpleNamespace(name=name, fileid="another-file")

    result = probe._confirm_remote_rename_v1113(
        Api(),
        target_path="/media/Demo (2026)",
        desired_name="Demo - S01E05 - 2160p.WEB-DL.mkv",
        file_id="file-5",
        attempts=1,
        interval=0,
    )
    assert result["confirmed"] is False
    assert "mismatch" in result["message"]


def test_cloudcollection_rename_only_persists_renamed_name_after_readback_confirmation():
    poll = dispatch_text.split("    def _poll_offline_source(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # 迅雷",
        1,
    )[0]
    assert 'rename_state="accepted"' in poll
    assert 'landing_stage="RENAME_ACCEPTED"' in poll
    assert "_confirm_remote_rename_v1113(" in poll
    assert 'rename_state="confirmed"' in poll
    assert 'rename_confirmed=True' in poll
    assert 'landing_stage="RENAME_CONFIRMED"' in poll
    assert 'rename_state="pending"' in poll
    assert 'landing_stage="RENAME_PENDING"' in poll
    accepted_block = poll.split('rename_state="accepted"', 1)[1].split(
        "if bool(confirm.get(\"confirmed\")):",
        1,
    )[0]
    assert "renamed_name=" not in accepted_block
