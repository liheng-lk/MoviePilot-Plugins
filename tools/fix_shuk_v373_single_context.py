from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
TESTS = ROOT / "tests" / "v3" / "shukguangyadisk"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing replacement anchor: {label}")
    return text.replace(old, new, 1)


# Episode helper must consume the already-recognized directory meta, not recognize_by_path again.
episode_path = PLUGIN / "organizer_episode_name_adapter_v3411.py"
episode = episode_path.read_text(encoding="utf-8")
episode = replace_once(
    episode,
    "    _is_tv_media,\n    _moviepilot_directory_context,\n    _moviepilot_tv_context_from_directory_meta,\n",
    "    _is_tv_media,\n    _moviepilot_tv_context_from_directory_meta,\n",
    "episode imports",
)
episode = replace_once(
    episode,
    '''def _ensure_tv_context(item: Any, kwargs: Dict[str, Any]) -> Tuple[bool, str]:
    media = kwargs.get("mediainfo")
    if _is_tv_media(media):
        kwargs["mtype"] = MediaType.TV
        return True, ""

    context, error = _moviepilot_directory_context(str(getattr(item, "path", "") or ""))
    meta = getattr(context, "meta_info", None) if context else None
    tv_media, tv_error = _moviepilot_tv_context_from_directory_meta(meta)
    if not tv_media:
        return False, str(tv_error or error or "MoviePilot 电视剧识别未确认")
    kwargs["mediainfo"] = tv_media
    kwargs["mtype"] = MediaType.TV
    return True, ""
''',
    '''def _ensure_tv_context(
    item: Any,
    kwargs: Dict[str, Any],
    directory_meta: Any,
) -> Tuple[bool, str]:
    media = kwargs.get("mediainfo")
    if _is_tv_media(media):
        kwargs["mtype"] = MediaType.TV
        return True, ""

    # 复用本轮唯一一次 MoviePilot 路径识别得到的 meta；禁止在同一 Preview 构建里二次 recognize_by_path。
    tv_media, tv_error = _moviepilot_tv_context_from_directory_meta(directory_meta)
    if not tv_media:
        return False, str(tv_error or "MoviePilot 电视剧识别未确认")
    kwargs["mediainfo"] = tv_media
    kwargs["mtype"] = MediaType.TV
    return True, ""
''',
    "ensure tv context",
)
episode = replace_once(
    episode,
    "    kwargs: Dict[str, Any],\n) -> Tuple[Dict[str, Any], Optional[str], str]:",
    "    kwargs: Dict[str, Any],\n    directory_meta: Any,\n) -> Tuple[Dict[str, Any], Optional[str], str]:",
    "apply signature",
)
episode = episode.replace("_ensure_tv_context(item, resolved)", "_ensure_tv_context(item, resolved, directory_meta)")
episode_path.write_text(episode, encoding="utf-8")


loss_path = PLUGIN / "organizer_loss_guard_v349.py"
loss = loss_path.read_text(encoding="utf-8")
loss = loss.replace("from app.schemas.types import MediaType\n", "")
loss = replace_once(
    loss,
    '''from .organizer_mp_folder_context_v346 import (
    _directory_fileitem,
    _is_monitor_root_folder_task,
    _is_tv_media,
    _moviepilot_directory_context,
    _moviepilot_tv_context_from_directory_meta,
    _normalize_result,
)
''',
    '''from .organizer_mp_folder_context_v346 import (
    _directory_fileitem,
    _moviepilot_directory_context,
)
''',
    "loss mp imports",
)
loss = replace_once(
    loss,
    '    media = getattr(context, "media_info", None) if context else None\n\n    kwargs: Dict[str, Any] = {',
    '    media = getattr(context, "media_info", None) if context else None\n    meta = getattr(context, "meta_info", None) if context else None\n\n    kwargs: Dict[str, Any] = {',
    "loss meta extraction",
)
loss = replace_once(
    loss,
    '''        directory_item,
        kwargs,
    )
''',
    '''        directory_item,
        kwargs,
        directory_meta=meta,
    )
''',
    "loss episode helper call",
)
loss_path.write_text(loss, encoding="utf-8")


# Extend the single v3.7.3 architecture contract rather than creating a micro-test file.
contract_path = TESTS / "test_organizer_phase2_v373_contract.py"
contract = contract_path.read_text(encoding="utf-8")
anchor = '''def test_v373_preserves_moviepilot_authority_and_fail_closed_boundaries():
'''
if anchor not in contract:
    raise RuntimeError("v373 contract anchor missing")
new_test = '''def test_v373_reuses_one_moviepilot_directory_recognition_context():
    build = LOSS[LOSS.index("def _build_moviepilot_kwargs"):LOSS.index("def _defer_unconfirmed_members")]
    assert build.count("_moviepilot_directory_context(") == 1
    assert 'meta = getattr(context, "meta_info", None)' in build
    assert "directory_meta=meta" in build
    assert "_moviepilot_directory_context(" not in EPISODE
    assert "_moviepilot_tv_context_from_directory_meta(directory_meta)" in EPISODE


'''
contract = contract.replace(anchor, new_test + anchor, 1)
contract_path.write_text(contract, encoding="utf-8")

print("v3.7.3 single MoviePilot recognition context preserved")
