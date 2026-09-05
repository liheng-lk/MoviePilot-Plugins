"""v1.8.0 Magnet/ED2K -> 光鸭原生云添加契约测试。

当前发布版本可以高于 1.8.0，但 v1.8 的原生云添加与 taskId 防重复契约必须继续成立。
"""

from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
TYPES = PLUGIN / "source_types_v180.py"
STORE = PLUGIN / "source_store_v180.py"
MULTI = PLUGIN / "multisource_v180.py"
SAFETY = PLUGIN / "offline_safety_v180.py"

entry_text = ENTRY.read_text(encoding="utf-8")
types_text = TYPES.read_text(encoding="utf-8")
store_text = STORE.read_text(encoding="utf-8")
multi_text = MULTI.read_text(encoding="utf-8")
safety_text = SAFETY.read_text(encoding="utf-8")


def test_v180_files_parse_as_python():
    for path, text in (
        (ENTRY, entry_text),
        (TYPES, types_text),
        (STORE, store_text),
        (MULTI, multi_text),
        (SAFETY, safety_text),
    ):
        ast.parse(text, filename=str(path))


def test_v180_contract_is_retained_by_current_runtime():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.12.12"
    assert 'plugin_version = "1.12.12"' in entry_text
    assert "GuangYaOfflineSafetyMixin" in entry_text
    assert "GuangYaMultiSourceMixin" in entry_text
    assert entry_text.index("GuangYaOfflineSafetyMixin,", entry_text.index("class GuangYaTransferAssistant")) < entry_text.index(
        "GuangYaMultiSourceMixin,", entry_text.index("class GuangYaTransferAssistant")
    )


def test_magnet_and_ed2k_normalization_and_stable_identity():
    ns = runpy.run_path(str(TYPES))
    magnet = ns["normalize_magnet"](
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Demo"
    )
    assert magnet["type"] == "magnet"
    assert magnet["identity"] == "0123456789abcdef0123456789abcdef01234567"
    assert magnet["name"] == "Demo"

    ed2k = ns["normalize_ed2k"](
        "ed2k://|file|Demo.S01E01.mkv|123456|0123456789abcdef0123456789abcdef|/"
    )
    assert ed2k["type"] == "ed2k"
    assert ed2k["size"] == 123456
    assert ed2k["identity"] == "0123456789abcdef0123456789abcdef"

    identity = ns["source_identity"]
    assert identity("magnet", magnet["identity"], 7) == identity("magnet", magnet["identity"], 7)
    assert identity("magnet", magnet["identity"], 7) != identity("magnet", magnet["identity"], 8)


def test_queued_task_is_inflight_not_pending_and_review_is_terminal():
    ns = runpy.run_path(str(TYPES))
    assert "queued" not in ns["SOURCE_PENDING_STATES"]
    assert "queued" in ns["SOURCE_INFLIGHT_STATES"]
    assert "needs_review" in ns["SOURCE_TERMINAL_STATES"]


def test_magnet_and_ed2k_have_no_moviepilot_downloader_or_bridge_code_path():
    combined = "\n".join([store_text, multi_text, safety_text]).lower()
    forbidden_code = (
        "from app.chain.download",
        "import downloadchain",
        "downloadchain(",
        "downloaderhelper(",
        "ed2k_dispatch_url",
        "ed2k_dispatch_token",
        "bridge_url",
        "bridge_token",
    )
    for token in forbidden_code:
        assert token not in combined, token
    assert '"/cloudcollection/v1/create_task"' in multi_text


def test_native_guangya_cloudcollection_endpoints_are_complete():
    for endpoint in (
        "/cloudcollection/v1/resolve_res",
        "/cloudcollection/v1/create_task",
        "/cloudcollection/v1/list_task",
        "/cloudcollection/v2/retry_task",
    ):
        assert endpoint in multi_text
    assert "_get_guangya_runtime" in multi_text
    assert "_offline_target_parent" in multi_text
    assert "api.get_folder(Path(target_path))" in multi_text


def test_existing_task_id_is_never_created_twice():
    assert "只要服务端任务已经存在" in safety_text
    submit = safety_text.split("    def _submit_offline_source(", 1)[1].split("    def _poll_offline_source(", 1)[0]
    assert "if task_id:" in submit
    assert "return self._poll_offline_source(source)" in submit
    assert "create_task" not in submit


def test_polling_transport_error_preserves_valid_server_task():
    poll = safety_text.split("    def _poll_offline_source(", 1)[1].split("    @staticmethod\n    def _source_public_view", 1)[0]
    assert 'state="waiting"' in poll
    assert "attempts=before_attempts" in poll
    assert '!= 5' in poll


def test_source_list_redacts_original_magnet_uri():
    public = safety_text.split("    @staticmethod\n    def _source_public_view", 1)[1].split("    def api_source_list", 1)[0]
    assert 'row.pop("uri"' in public
    assert "urn:btih" in public
    assert "uri_preview" in public


def test_fixed_route_is_activated_when_external_source_is_bound():
    upsert = store_text.split("    def _upsert_source(", 1)[1].split("    def _update_source(", 1)[0]
    assert "self._add_selected_subscription(sid, persist=True)" in upsert
    assert "固定分流硬门禁" in upsert


def test_viewing_ingest_is_subscription_source_extension():
    method = multi_text.split("    def api_viewing_ingest(", 1)[1].split("    def get_api(", 1)[0]
    assert "_resolve_source_subscription" in method
    assert "_upsert_source" in method
    assert 'origin="viewing"' in method
    assert "_spawn_source_dispatch" in method
    assert '"/viewing/ingest"' in multi_text


def test_v180_status_page_implementation_is_retained_but_final_ui_can_replace_it():
    page = multi_text.split("    def get_page(self):", 1)[1].split("    def _build_selfcheck", 1)[0]
    assert "光鸭转存 · 多来源控制台" in page
    assert "Magnet / ED2K 云添加任务" in page
    assert "return [dashboard, sources_panel, advanced_header, *existing_pages]" in page
    assert "光鸭原生云添加" in multi_text
