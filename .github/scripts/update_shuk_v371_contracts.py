from pathlib import Path

TEST = Path("tests/v3/shukguangyadisk")


def replace_function(path: Path, name: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    marker = f"def {name}():\n"
    start = text.find(marker)
    if start < 0:
        raise AssertionError(f"contract function missing: {path.name}::{name}")
    next_def = text.find("\ndef ", start + len(marker))
    end = len(text) if next_def < 0 else next_def + 1
    path.write_text(text[:start] + replacement.rstrip() + "\n\n" + text[end:], encoding="utf-8")


release = TEST / "test_release_v370.py"
replace_function(
    release,
    "test_v370_status_exposes_policy_version_separately_from_legacy_hardening",
    '''def test_v370_status_exposes_policy_version_separately_from_legacy_hardening():
    import re

    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    match = re.search(r'"organizer_policy_version": "v(\\d+)\\.(\\d+)\\.(\\d+)"', execution)
    assert match, "organizer policy version missing"
    assert tuple(map(int, match.groups())) >= (3, 7, 0)
    assert '"runtime_hardening": "v3.6.20"' in execution''',
)
replace_function(
    release,
    "test_v370_startup_banner_uses_current_policy_semantics_not_old_conflict_version",
    '''def test_v370_startup_banner_uses_current_policy_semantics_not_old_conflict_version():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    conflict = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
    assert "【整理核心 v3.7.1】policy 执行链已显式接管" in execution
    assert "【v3.5.3】电影重复目标与剧集局部冲突消歧已启用" not in conflict
    assert "install_conflict_resolution_v353" not in conflict''',
)

season = TEST / "test_season_context_v358.py"
replace_function(
    season,
    "test_v358_installs_after_v356",
    '''def test_v358_remains_installed_while_v356_migration_is_explicit_in_execution_core():
    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")
    assert 'install_preview_retry_wakeup_v356()' not in CANDIDATE
    assert 'install_season_context_v358()' in CANDIDATE
    assert '_wake_legacy_preview_retries(self)' in execution
    assert '_v371_preview_retry_migration_checked' in execution''',
)

print("updated stale contracts for explicit v3.7.1 core")
