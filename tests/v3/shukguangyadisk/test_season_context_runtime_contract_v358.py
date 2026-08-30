from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_season_context_v358.py").read_text(encoding="utf-8")
MP_FOLDER = (PLUGIN / "organizer_mp_folder_context_v346.py").read_text(encoding="utf-8")


def test_v358_preserves_moviepilot_transfer_owner_boundary():
    assert 'kwargs["season"] = season' in PATCH
    assert 'TransferChain().do_transfer' not in PATCH
    assert 'target_path' not in PATCH
    assert 'rename_format' not in PATCH


def test_v358_runs_on_same_kwargs_builder_used_by_preview_and_real_transfer():
    assert 'previous_build = _loss_guard._build_moviepilot_kwargs' in PATCH
    assert '_loss_guard._build_moviepilot_kwargs = build' in PATCH
    assert '"background": False' in MP_FOLDER
    assert '"manual": False' in MP_FOLDER


def test_v358_does_not_guess_multiseason_without_evidence():
    assert 'if len(media_seasons) > 1:' in PATCH
    assert 'MoviePilot 已确认该剧存在多个正季' in PATCH
    assert 'return transfer_chain, directory_item, kwargs, message' in PATCH
