from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
LOSS = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
EPISODE = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
CATEGORY = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")


def test_v373_removes_three_recognition_preview_runtime_installers():
    for token in (
        "install_episode_name_adapter_v3411",
        "install_episode_sample_bridge_v3411",
        "install_category_consistency_v3412",
    ):
        assert token not in CANDIDATE
    assert not (PLUGIN / "organizer_episode_sample_bridge_v3411.py").exists()


def test_v373_loss_guard_explicitly_owns_preview_context_order():
    assert "apply_episode_name_adapter(" in LOSS
    assert "apply_category_consistency(" in LOSS
    assert "audit_episode_expectations(" in LOSS
    build = LOSS[LOSS.index("def _build_moviepilot_kwargs"):LOSS.index("def _defer_unconfirmed_members")]
    assert build.index("_moviepilot_directory_context(") < build.index("apply_episode_name_adapter(")
    assert build.index("apply_episode_name_adapter(") < build.index("apply_category_consistency(")
    audit = LOSS[LOSS.index("def _audit_preview"):LOSS.index("def _build_moviepilot_kwargs")]
    assert "audit_episode_expectations(" in audit

def test_v373_helpers_are_pure_and_do_not_patch_runtime_functions():
    for source in (EPISODE, CATEGORY):
        assert "_build_moviepilot_kwargs =" not in source
        assert "_audit_preview =" not in source
        assert "GuangYaQueueRecoveryMixin._execute_isolated_transfer =" not in source
    assert "ContextVar" not in EPISODE


def test_v373_preserves_moviepilot_authority_and_fail_closed_boundaries():
    assert "recommend_episode_format(" in EPISODE
    assert "FormatParser(eformat=template)" in EPISODE
    assert "CategoryHelper" in CATEGORY
    assert "return resolved, category_error" in CATEGORY
    for forbidden in (
        "tmdb_id=", "media_id=", "DirectoryHelper().get_dir(",
        "self._guangya_api.move", "self._guangya_api.copy",
    ):
        assert forbidden not in EPISODE
        assert forbidden not in CATEGORY
