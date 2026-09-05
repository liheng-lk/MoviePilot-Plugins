from pathlib import Path

TEST = Path("tests/v3/shukguangyadisk")


def update(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"stale contract patch point changed: {label}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# v3.7.0 release contract becomes a release-floor contract: Phase 2 may advance policy version,
# while plugin/public version migration is validated separately at release staging.
path = TEST / "test_release_v370.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '''def test_v370_status_exposes_policy_version_separately_from_legacy_hardening():\n    execution = EXECUTION.read_text(encoding="utf-8")\n    assert '"organizer_policy_version": "v3.7.0"' in execution\n    assert '"runtime_hardening": "v3.6.20"' in execution\n''',
    '''def test_v370_status_exposes_policy_version_separately_from_legacy_hardening():\n    import re\n\n    execution = EXECUTION.read_text(encoding="utf-8")\n    match = re.search(r'"organizer_policy_version": "v(\\d+)\\.(\\d+)\\.(\\d+)"', execution)\n    assert match, "organizer policy version missing"\n    assert tuple(map(int, match.groups())) >= (3, 7, 0)\n    assert '"runtime_hardening": "v3.6.20"' in execution\n''',
    1,
)
text = text.replace(
    '''def test_v370_startup_banner_uses_current_policy_semantics_not_old_conflict_version():\n    conflict = CONFLICT.read_text(encoding="utf-8")\n    assert "【整理策略 v3.7.0】统一文件处置已启用" in conflict\n    assert "【v3.5.3】电影重复目标与剧集局部冲突消歧已启用" not in conflict\n''',
    '''def test_v370_startup_banner_uses_current_policy_semantics_not_old_conflict_version():\n    execution = EXECUTION.read_text(encoding="utf-8")\n    conflict = CONFLICT.read_text(encoding="utf-8")\n    assert "【整理核心 v3.7.1】policy 执行链已显式接管" in execution\n    assert "【v3.5.3】电影重复目标与剧集局部冲突消歧已启用" not in conflict\n    assert "install_conflict_resolution_v353" not in conflict\n''',
    1,
)
path.write_text(text, encoding="utf-8")

# Season context remains an active compatibility helper, but it no longer needs to be ordered after
# a v3.5.6 scan monkey-patch. The legacy retry migration is now explicit in Execution init.
path = TEST / "test_season_context_v358.py"
text = path.read_text(encoding="utf-8")
old = '''def test_v358_installs_after_v356():\n    wake_pos = CANDIDATE.index('install_preview_retry_wakeup_v356()')\n    season_pos = CANDIDATE.index('install_season_context_v358()')\n    assert season_pos > wake_pos\n'''
new = '''def test_v358_remains_installed_while_v356_migration_is_explicit_in_execution_core():\n    execution = (PLUGIN / "organizer_execution_v360.py").read_text(encoding="utf-8")\n    assert 'install_preview_retry_wakeup_v356()' not in CANDIDATE\n    assert 'install_season_context_v358()' in CANDIDATE\n    assert '_wake_legacy_preview_retries(self)' in execution\n    assert '_v371_preview_retry_migration_checked' in execution\n'''
if old not in text:
    raise AssertionError("season v358 stale order contract changed")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

print("updated stale contracts for explicit v3.7.1 core")
