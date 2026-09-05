from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests" / "v3" / "guangyatransferassistant"

# These files failed only because they deliberately assert the current public runtime/manifest version.
# Historical source-layer markers (CORE/FINAL/FENCE/ALIAS/SEASON/SOURCE, etc.) must remain untouched.
CURRENT_RELEASE_FILES = {
    "test_airing_scheduler_v1120.py",
    "test_airing_weekly_v1121.py",
    "test_command_bridge_v1128.py",
    "test_config_providers_v192.py",
    "test_content_resilience_v1105.py",
    "test_core_pipeline_v11214.py",
    "test_dispatch_policy_v1125.py",
    "test_episode_compat_v171.py",
    "test_fast_recall_v1126.py",
    "test_gying_auth_v1107.py",
    "test_gying_autologin_v1109.py",
    "test_gying_hardening_v193.py",
    "test_gying_observability_v1104.py",
    "test_gying_pansou_v1110.py",
    "test_gying_pow_v1111.py",
    "test_gying_transport_v1108.py",
    "test_gying_xunlei_recall_v1125.py",
    "test_mp_sdk_compat_v195.py",
    "test_multisource_v180_contract.py",
    "test_page_perf_v1123.py",
    "test_plugin_contract.py",
    "test_release_v1109_marker.py",
    "test_release_v1111_marker.py",
    "test_release_v11213_marker.py",
    "test_release_v1125_marker.py",
    "test_resource_gate_v1127.py",
    "test_resource_planner_v190_contract.py",
    "test_status_ui_v191.py",
    "test_subscribe_contract_v196.py",
    "test_v1100_ui_runtime.py",
    "test_v180_metadata_contract.py",
    "test_viewing_dispatch_v1113.py",
    "test_xunlei_flash_v193.py",
    "test_xunlei_hardening_v193.py",
}

# Only these variable/context names denote current release truth in the historical contract suite.
PUBLIC_CONTEXT_TOKENS = (
    "ENTRY",
    "entry_text",
    "entry)",
    "entry,",
    " entry",
    "PACKAGE",
    "package[",
    "LOCAL",
    "local[",
    "PLUGIN_JSON",
    "plugin[\"version\"]",
    "plugin['version']",
)


def is_public_release_line(line: str) -> bool:
    return any(token in line for token in PUBLIC_CONTEXT_TOKENS)


def migrate_file(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    out = []
    changes = 0
    for line in original.splitlines(keepends=True):
        updated = line
        if '"1.12.14"' in updated and is_public_release_line(updated):
            updated = updated.replace('"1.12.14"', '"1.12.15"')
        if '"20260905-r60"' in updated and is_public_release_line(updated):
            updated = updated.replace('"20260905-r60"', '"20260905-r61"')

        # A few old tests intentionally name the runtime-entry text simply `text`.
        if path.name == "test_episode_compat_v171.py":
            updated = updated.replace(
                'assert \'build_id = "20260905-r60"\' in text',
                'assert \'build_id = "20260905-r61"\' in text',
            )

        if updated != line:
            changes += 1
        out.append(updated)

    rewritten = "".join(out)
    if changes <= 0:
        raise SystemExit(f"{path}: expected current-release migration but changed 0 lines")
    path.write_text(rewritten, encoding="utf-8")
    return changes


def verify_no_stale_public_assertions() -> None:
    stale = []
    for path in sorted(TEST_ROOT.glob("test_*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not is_public_release_line(line):
                continue
            if '"1.12.14"' in line or '"20260905-r60"' in line:
                stale.append(f"{path.name}:{lineno}: {line.strip()}")
    # `test_episode_compat_v171.py` uses a generic local `text`; verify it explicitly too.
    ep = TEST_ROOT / "test_episode_compat_v171.py"
    for lineno, line in enumerate(ep.read_text(encoding="utf-8").splitlines(), 1):
        if 'build_id = "20260905-r60"' in line and " in text" in line:
            stale.append(f"{ep.name}:{lineno}: {line.strip()}")
    if stale:
        raise SystemExit("stale current-public release assertions remain:\n" + "\n".join(stale))


def main() -> None:
    changed = 0
    for name in sorted(CURRENT_RELEASE_FILES):
        path = TEST_ROOT / name
        if not path.exists():
            raise SystemExit(f"missing expected contract file: {path}")
        changed += migrate_file(path)
    verify_no_stale_public_assertions()
    print(f"migrated {changed} current-public release assertion lines across {len(CURRENT_RELEASE_FILES)} files")


if __name__ == "__main__":
    main()
