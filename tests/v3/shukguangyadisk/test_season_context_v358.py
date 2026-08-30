from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_season_context_v358.py").read_text(encoding="utf-8")
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_v358_passes_season_only_through_moviepilot_public_argument():
    for token in (
        'kwargs["season"] = season',
        'MoviePilot 公开的 ``season`` 参数',
        '不拼接目标路径、不修改命名模板',
        'if plan_error or not _is_tv_kwargs',
    ):
        assert token in PATCH, token


def test_v358_season_evidence_priority_is_conservative():
    for token in (
        'return path_season, "season_directory", None',
        'return member_season, "member_sxe", None',
        'return next(iter(media_seasons)), "moviepilot_single_season", None',
        'if len(explicit) > 1:',
        '目录季号 S{path_season:02d} 与文件明确季号 S{member_season:02d} 冲突',
        'MoviePilot 已确认该剧存在多个正季，但当前目录和文件名都没有可靠季号',
    ):
        assert token in PATCH, token


def test_v358_ignores_specials_for_single_season_fallback():
    assert 'return number if number > 0 else None' in PATCH
    assert 'Season 0 不参与单季判断' in PATCH
    assert 'for attr in ("seasons", "season_years")' in PATCH
    assert 'season_info' in PATCH


def test_v358_wakes_only_old_empty_season_directory_failures():
    for token in (
        '_EMPTY_SEASON_RETRY = re.compile(r"Season\\s+目录获取失败"',
        'reason = str(raw.get("last_error") or "")',
        'if not _EMPTY_SEASON_RETRY.search(reason):',
        'row["retry_at"] = 0',
        '其它 retry 保持原样',
    ):
        assert token in PATCH, token


def test_v358_installs_after_v356():
    wake_pos = CANDIDATE.index('install_preview_retry_wakeup_v356()')
    season_pos = CANDIDATE.index('install_season_context_v358()')
    assert season_pos > wake_pos
    assert 'from .organizer_season_context_v358 import install_season_context_v358' in CANDIDATE


def test_v358_release_metadata_is_consistent():
    plugin_meta = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package_meta = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    assert plugin_meta["version"] == "3.5.8"
    assert package_meta["ShukGuangYaDisk"]["version"] == "3.5.8"
    assert 'plugin_version = "3.5.8"' in ENTRY
    assert '?v=3.5.8' in REMOTE
    assert 'v3.5.8' in plugin_meta["history"]


def test_v358_has_runtime_diagnostics():
    for token in (
        '【v3.5.8】【季号上下文】MoviePilot season=%s',
        '【v3.5.8】【升级自愈】发现空 Season 目标失败 retry=%s',
        '【v3.5.8】电视剧季号上下文补全与空季重试自愈已启用',
    ):
        assert token in PATCH, token
