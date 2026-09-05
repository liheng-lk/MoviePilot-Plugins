from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3/shukguangyadisk"


def test_v371_version_rename_requires_thread_local_policy_context():
    conflict = (PLUGIN / "organizer_conflict_resolution_v353.py").read_text(encoding="utf-8")
    assert 'context = getattr(_RENAME_CONTEXT, "value", None)' in conflict
    assert 'context.get("plugin_id") != id(plugin)' in conflict
    assert 'if storage not in valid_storages:' in conflict
