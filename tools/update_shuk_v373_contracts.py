from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests" / "v3" / "shukguangyadisk"


def replace_function(text: str, name: str, source: str) -> str:
    marker = f"\ndef {name}("
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"test not found: {name}")
    start += 1
    next_start = text.find("\ndef ", start + 1)
    if next_start < 0:
        next_start = len(text)
    return text[:start] + source.rstrip() + "\n\n" + text[next_start + 1:]


# Folder identity stays after explicit recognition/preview context, but no longer depends on
# a category runtime installer existing in candidate_filter.
path = TESTS / "test_folder_identity_v350.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")\n',
    'FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")\n'
    'LOSS = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")\n',
)
text = replace_function(
    text,
    "test_folder_identity_wraps_episode_and_category_chain_before_rename_diagnostics",
    '''def test_folder_identity_follows_explicit_episode_and_category_context_before_rename_diagnostics():
    assert "from .organizer_folder_identity_v350 import install_folder_identity_v350" in FILTER
    assert "install_folder_identity_v350()" in FILTER
    assert "install_category_consistency_v3412" not in FILTER
    assert "apply_episode_name_adapter(" in LOSS
    assert "apply_category_consistency(" in LOSS
    assert LOSS.index("apply_episode_name_adapter(") < LOSS.index("apply_category_consistency(")
    assert FILTER.index("install_folder_identity_v350()") < FILTER.index("install_rename_diagnostics_v3414()")''',
)
path.write_text(text, encoding="utf-8")


# Loss guard now delegates episode/category compatibility explicitly instead of calling the
# historical episode-format helper through a patched symbol.
path = TESTS / "test_loss_guard_v349.py"
text = path.read_text(encoding="utf-8")
text = replace_function(
    text,
    "test_guard_does_not_build_a_second_naming_or_classification_policy",
    '''def test_guard_does_not_build_a_second_naming_or_classification_policy():
    for forbidden in (
        "RENAME_FORMAT(",
        "get_rename_path(",
        "DirectoryHelper().get_dir(",
        "tmdb_id=",
        "media_id=",
        "self._guangya_api.move",
        "self._guangya_api.copy",
    ):
        assert forbidden not in GUARD, forbidden
    assert "_moviepilot_directory_context" in GUARD
    assert "apply_episode_name_adapter(" in GUARD
    assert "apply_category_consistency(" in GUARD
    assert "audit_episode_expectations(" in GUARD''',
)
path.write_text(text, encoding="utf-8")


# Architecture contract binds to executable ordering, not an exact explanatory sentence.
path = TESTS / "test_organizer_phase2_v373_contract.py"
text = path.read_text(encoding="utf-8")
text = replace_function(
    text,
    "test_v373_loss_guard_explicitly_owns_preview_context_order",
    '''def test_v373_loss_guard_explicitly_owns_preview_context_order():
    assert "apply_episode_name_adapter(" in LOSS
    assert "apply_category_consistency(" in LOSS
    assert "audit_episode_expectations(" in LOSS
    build = LOSS[LOSS.index("def _build_moviepilot_kwargs"):LOSS.index("def _defer_unconfirmed_members")]
    assert build.index("_moviepilot_directory_context(") < build.index("apply_episode_name_adapter(")
    assert build.index("apply_episode_name_adapter(") < build.index("apply_category_consistency(")
    audit = LOSS[LOSS.index("def _audit_preview"):LOSS.index("def _build_moviepilot_kwargs")]
    assert "audit_episode_expectations(" in audit''',
)
path.write_text(text, encoding="utf-8")

print("v3.7.3 stale architecture contracts migrated")
