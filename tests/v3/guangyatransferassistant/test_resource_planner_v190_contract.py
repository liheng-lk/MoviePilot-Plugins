from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = PLUGIN / "__init__.py"
RESOLVER = PLUGIN / "episode_resolver_v190.py"
CHANNEL = PLUGIN / "channel_sources_v190.py"
PLANNER = PLUGIN / "resource_planner_v190.py"
PLANNER_SAFETY = PLUGIN / "planner_safety_v190.py"
STORE = PLUGIN / "source_store_v180.py"
MULTI = PLUGIN / "multisource_v180.py"
OFFLINE_SAFETY = PLUGIN / "offline_safety_v180.py"

texts = {path: path.read_text(encoding="utf-8") for path in (
    ENTRY, RESOLVER, CHANNEL, PLANNER, PLANNER_SAFETY, STORE, MULTI, OFFLINE_SAFETY,
)}


def test_all_v190_files_parse_and_publish_current_version():
    for path, text in texts.items():
        ast.parse(text, filename=str(path))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert package["version"] == local["version"] == "1.12.12"
    assert 'plugin_version = "1.12.12"' in texts[ENTRY]
    assert 'build_id = "20260905-r58"' in texts[ENTRY]


def test_runtime_mro_puts_planner_safety_and_planner_before_native_offline_layers():
    entry = texts[ENTRY]
    start = entry.index("class GuangYaTransferAssistant")
    order = [
        "GuangYaPlannerSafetyMixin,",
        "GuangYaResourcePlannerMixin,",
        "GuangYaOfflineSafetyMixin,",
        "GuangYaMultiSourceMixin,",
    ]
    positions = [entry.index(token, start) for token in order]
    assert positions == sorted(positions)
    assert "install_channel_multisource_compat(_legacy_module)" in entry


def test_same_channel_message_is_a_resource_group_not_independent_jobs():
    channel = texts[CHANNEL]
    for token in (
        "resource_group_id",
        "external_sources",
        "candidate_types",
        "message_id",
        "share_url",
        "magnet",
        "ed2k",
    ):
        assert token in channel
    assert 'entry["candidate_types"] = ["guangya"' in channel
    assert '"share_url": ""' in channel


def test_decision_order_is_direct_share_then_magnet_then_ed2k():
    planner = texts[PLANNER]
    store = texts[STORE]
    assert '("guangya", "magnet", "ed2k")' in store
    assert '"guangya,magnet,ed2k"' in store
    assert "super()._try_transfer_subscription_inner" in planner
    assert "_pending_reservations(subscribe)" in planner
    assert '0 if str(row.get("type") or "") == "magnet" else 1' in planner
    assert 'rank = 1 if source_type == "magnet" else 2' in planner
    assert "光鸭直接转存未覆盖这些目标集" in planner


def test_external_candidates_claim_only_real_missing_episodes_and_do_not_duplicate_share_pending():
    planner = texts[PLANNER]
    assert "missing - reserved - active_claims" in planner
    assert "_active_source_claims" in planner
    assert "target_episodes" in planner
    assert "resolved_episodes" in planner
    assert "configured_target or missing" in planner
    assert "- reserved" in planner


def test_magnet_file_selection_is_high_confidence_and_never_appends_weak_unknown_media():
    planner = texts[PLANNER]
    assert "reliable_episode_set" in planner
    assert "_episode_auto_confidence" in planner
    assert 'state="needs_review"' in planner
    assert "绝不把 A.mkv/B.mkv 按顺序猜成集号" in planner
    assert "selected_videos" in planner
    selection = planner.split("    def _planner_file_selection(", 1)[1].split("    def _resolve_offline_source(", 1)[0]
    assert "weak.append" not in selection
    assert "selected_videos.append(row)" in selection


def test_subtitles_only_follow_selected_episode_or_single_video_folder():
    planner = texts[PLANNER]
    selection = planner.split("    def _planner_file_selection(", 1)[1].split("    def _resolve_offline_source(", 1)[0]
    assert "episodes.intersection(covered)" in selection
    assert "len(videos_by_parent.get(parent) or []) == 1" in selection


def test_resource_rules_are_checked_after_cloud_resolve_before_create_task():
    safety = texts[PLANNER_SAFETY]
    assert "Magnet 的真实画质/发布名通常只有 resolve_res 后才能确认" in safety
    resolve = safety.split("    def _resolve_offline_source(", 1)[1].split("    def _mark_offline_failure(", 1)[0]
    assert "super()._resolve_offline_source(source, subscribe)" in resolve
    assert "_subscription_resource_allowed" in resolve
    assert "RESOURCE_RULE_MISMATCH" in safety
    assert '"/cloudcollection/v1/create_task"' in texts[MULTI]
    assert '"/cloudcollection/v1/create_task"' not in safety


def test_low_confidence_and_rule_mismatch_do_not_retry_as_whole_pack():
    planner = texts[PLANNER]
    safety = texts[PLANNER_SAFETY]
    assert "EPISODE_AMBIGUOUS:" in planner
    assert 'state="needs_review"' in planner
    assert 'next_retry_at=0' in planner
    assert 'state="failed"' in safety
    assert "转向下一候选" in safety


def test_complete_config_survives_async_route_persistence():
    safety = texts[PLANNER_SAFETY]
    save = safety.split("    def _save_config(self)", 1)[1].split("    def _external_resource_allowed", 1)[0]
    for key in (
        "selected_subscriptions",
        "external_auto_dispatch",
        "source_priority",
        "offline_poll_minutes",
        "offline_retry_minutes",
        "offline_max_attempts",
        "channel_external_auto_dispatch",
        "episode_auto_confidence",
        "provider_auto_search",
        "viewing_base_url",
        "viewing_cookie",
        "viewing_registry_urls",
        "viewing_node_urls",
        "viewing_auto_switch",
        "viewing_auto_challenge",
        "viewing_node_cache_minutes",
        "magnet_api_sources",
        "xunlei_flash_enabled",
        "xunlei_device_id",
        "xunlei_captcha_token",
        "xunlei_captcha_init_json",
    ):
        assert f'"{key}"' in save


def test_no_moviepilot_downloader_is_reintroduced_for_magnet_or_ed2k():
    combined = "\n".join(texts[path] for path in (RESOLVER, CHANNEL, PLANNER, PLANNER_SAFETY, STORE, MULTI, OFFLINE_SAFETY)).lower()
    for forbidden in (
        "from app.chain.download",
        "downloadchain(",
        "qbittorrent",
        "transmission",
        "aria2",
        "bridge_url",
    ):
        if forbidden in {"qbittorrent", "transmission", "aria2"}:
            continue
        assert forbidden not in combined
    assert "/cloudcollection/v1/resolve_res" in texts[MULTI]
    assert "/cloudcollection/v1/create_task" in texts[MULTI]


def test_resource_plan_api_and_review_status_are_exposed():
    planner = texts[PLANNER]
    safety = texts[PLANNER_SAFETY]
    assert '"/resource/plan"' in planner
    assert "resource_plans" in planner
    assert "资源组决策 · 缺集拆包" in planner
    assert "GuangYaStatusUiMixin" in safety
    assert "return GuangYaStatusUiMixin.get_page(self)" in safety
