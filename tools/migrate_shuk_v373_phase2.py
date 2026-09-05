from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
TESTS = ROOT / "tests" / "v3" / "shukguangyadisk"


def replace_function(text: str, name: str, new_source: str) -> str:
    marker = f"\ndef {name}("
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"function not found: {name}")
    start += 1
    next_start = text.find("\ndef ", start + 1)
    if next_start < 0:
        raise RuntimeError(f"next function not found after: {name}")
    return text[:start] + new_source.rstrip() + "\n\n" + text[next_start + 1 :]


# 1) Episode adapter becomes a pure helper surface. No runtime monkey patching.
episode_path = PLUGIN / "organizer_episode_name_adapter_v3411.py"
episode = episode_path.read_text(encoding="utf-8")
episode = episode.replace("from . import organizer_loss_guard_v349 as _loss_guard\n", "")
install_marker = "\ndef install_episode_name_adapter_v3411() -> None:\n"
install_start = episode.find(install_marker)
if install_start < 0:
    raise RuntimeError("episode installer marker not found")

episode_tail = r'''
def apply_episode_name_adapter(
    plugin: Any,
    item: Any,
    transfer_chain: Any,
    directory_item: Any,
    kwargs: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str], str]:
    """显式构建 MoviePilot 集数上下文，不改写其它模块函数。"""
    resolved = dict(kwargs or {})

    existing_epformat = resolved.get("epformat")
    if existing_epformat:
        template = str(getattr(existing_epformat, "format", "") or "")
        expectations = _validated_expectations(template, _media_members(item), require_tokens=False) or {}
        if expectations:
            _attach_expectations(plugin, item, expectations, "moviepilot_existing")
        return resolved, None, "moviepilot_existing"

    # 唯一一次 MoviePilot 推荐：直接把当前 folder envelope 的整组成员传入公开 API。
    epformat, expectations, source = _mp_member_recommend(
        plugin,
        transfer_chain,
        directory_item,
        item,
    )
    if epformat:
        ok, error = _ensure_tv_context(item, resolved)
        if not ok:
            return resolved, error, source
        resolved["epformat"] = epformat
        if expectations:
            _attach_expectations(plugin, item, expectations, source)
        logger.info(
            "【光鸭云盘助手】【集数适配】MoviePilot 使用整组文件生成集数模板: %s -> %s",
            item.path,
            epformat.format,
        )
        return resolved, None, source

    # MoviePilot 未推荐时，仅对集号位置做兼容推导；仍必须经 MP FormatParser 整组反向验证。
    fallback, expectations, fallback_reason = _fallback_episode_format(item)
    if not fallback:
        logger.debug(
            "【光鸭云盘助手】【集数适配】未启用弱命名兼容模板: %s - MP=%s；fallback=%s",
            item.path,
            source,
            fallback_reason,
        )
        return resolved, None, f"{source};fallback={fallback_reason}"

    ok, error = _ensure_tv_context(item, resolved)
    if not ok:
        return resolved, error, fallback_reason
    resolved["epformat"] = fallback
    _attach_expectations(plugin, item, expectations, "validated_compatibility")
    logger.info(
        "【光鸭云盘助手】【集数适配】MoviePilot 原推荐未覆盖该命名，已生成并验证兼容模板: %s -> %s；成员=%s",
        item.path,
        fallback.format,
        len(expectations),
    )
    return resolved, None, "validated_compatibility"


def audit_episode_expectations(
    plugin: Any,
    item: Any,
    payload: Dict[str, Any],
    details: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """在基础 Preview 唯一性校验之后复核 MoviePilot 最终 season/episode。"""
    expectations = dict(getattr(item, "_guangya_episode_expectations_v3411", {}) or {})
    merged = dict(details or {})
    if not expectations:
        return True, "", merged
    if not isinstance(payload, dict):
        return False, "MoviePilot 预览结果无法执行集号复核", merged

    preview_rows = [row for row in (payload.get("items") or []) if isinstance(row, dict)]
    by_source = {
        plugin._organize_normalize_path(str(row.get("source") or "")): row
        for row in preview_rows
        if row.get("source")
    }
    mismatches: List[str] = []
    for source_path, expected in expectations.items():
        row = by_source.get(source_path)
        if not row:
            mismatches.append(f"{expected.get('name')} 未出现在预览")
            continue
        actual_episode = _to_int(row.get("episode"))
        actual_end = _to_int(row.get("episode_end"))
        actual_season = _to_int(row.get("season"))
        expected_episode = _to_int(expected.get("episode"))
        expected_end = _to_int(expected.get("episode_end"))
        expected_season = _to_int(expected.get("season"))
        if actual_episode != expected_episode:
            mismatches.append(
                f"{expected.get('name')} 期望E{expected_episode}但MoviePilot解析为E{actual_episode}"
            )
            continue
        if expected_end is not None and actual_end != expected_end:
            mismatches.append(
                f"{expected.get('name')} 期望结束集E{expected_end}但MoviePilot解析为E{actual_end}"
            )
            continue
        if expected_season is not None and actual_season not in (None, expected_season):
            mismatches.append(
                f"{expected.get('name')} 期望S{expected_season}但MoviePilot解析为S{actual_season}"
            )

    merged["episode_adapter"] = {
        "source": str(getattr(item, "_guangya_episode_adapter_source_v3411", "") or ""),
        "validated": len(expectations),
        "mismatches": mismatches[:20],
    }
    if mismatches:
        return (
            False,
            f"集号二次校验失败 {len(mismatches)} 个：" + "；".join(mismatches[:6]),
            merged,
        )
    return True, "", merged


__all__ = [
    "apply_episode_name_adapter",
    "audit_episode_expectations",
    "_episode_token",
    "_fallback_episode_format",
]
'''
episode = episode[:install_start] + "\n" + episode_tail.lstrip("\n")
episode_path.write_text(episode, encoding="utf-8")


# 2) Category consistency becomes a pure explicit helper.
category_path = PLUGIN / "organizer_category_consistency_v3412.py"
category = category_path.read_text(encoding="utf-8")
category = category.replace("from . import organizer_loss_guard_v349 as _loss_guard\n", "")
category_marker = "\ndef install_category_consistency_v3412() -> None:\n"
category_start = category.find(category_marker)
if category_start < 0:
    raise RuntimeError("category installer marker not found")
category_tail = r'''
def apply_category_consistency(
    item: Any,
    kwargs: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """按 MoviePilot 当前 CategoryHelper 收口 mediainfo.category；失败时 fail closed。"""
    resolved = dict(kwargs or {})
    media = resolved.get("mediainfo")
    if not media:
        return resolved, None

    reconciled, diagnostics, category_error = _reconcile_moviepilot_category(media)
    if category_error:
        logger.error(
            "【光鸭云盘助手】【分类一致性】已阻止真实整理，无法使用 MoviePilot 当前分类规则核验: %s - %s",
            getattr(item, "path", ""),
            category_error,
        )
        return resolved, category_error

    resolved["mediainfo"] = reconciled
    media_type = getattr(reconciled, "type", None)
    if media_type:
        resolved["mtype"] = media_type

    current = diagnostics.get("current_category") or "未分类"
    expected = diagnostics.get("moviepilot_category")
    expected_text = expected if expected else "未分类"
    origin = ",".join(diagnostics.get("origin_country") or []) or "-"
    production = ",".join(diagnostics.get("production_countries") or []) or "-"
    language = diagnostics.get("original_language") or "-"

    if diagnostics.get("corrected"):
        logger.warning(
            "【光鸭云盘助手】【分类一致性】识别上下文分类与 MoviePilot 当前 category.yaml 不一致，"
            "已使用 MP 当前结果: %s -> %s；origin_country=%s；production_countries=%s；original_language=%s",
            current,
            expected_text,
            origin,
            production,
            language,
        )
    else:
        logger.info(
            "【光鸭云盘助手】【分类一致性】MoviePilot 当前分类=%s；origin_country=%s；"
            "production_countries=%s；original_language=%s",
            expected_text,
            origin,
            production,
            language,
        )
    return resolved, None


__all__ = [
    "apply_category_consistency",
    "_moviepilot_current_category",
    "_reconcile_moviepilot_category",
]
'''
category = category[:category_start] + "\n" + category_tail.lstrip("\n")
category_path.write_text(category, encoding="utf-8")


# 3) Loss guard explicitly owns build/audit ordering.
loss_path = PLUGIN / "organizer_loss_guard_v349.py"
loss = loss_path.read_text(encoding="utf-8")
loss = loss.replace("    _moviepilot_episode_format,\n", "")
import_anchor = "from .organizer_mp_folder_context_v346 import (\n"
if import_anchor not in loss:
    raise RuntimeError("loss guard import anchor missing")
# Add pure helper imports after the mp context import block.
mp_block_end = loss.find(")\n\n", loss.find(import_anchor))
if mp_block_end < 0:
    raise RuntimeError("loss guard mp import block end missing")
mp_block_end += 3
helper_imports = (
    "from .organizer_episode_name_adapter_v3411 import (\n"
    "    apply_episode_name_adapter,\n"
    "    audit_episode_expectations,\n"
    ")\n"
    "from .organizer_category_consistency_v3412 import apply_category_consistency\n\n"
)
loss = loss[:mp_block_end] + helper_imports + loss[mp_block_end:]

new_audit = r'''def _audit_preview(plugin: Any, item: _FolderBatchEnvelope, result: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """核对成员唯一目标，再显式执行弱命名集号终态复核。"""
    ok, payload, error = _preview_result(result)
    if not ok or payload is None:
        return False, error, {"preview_total": 0, "expected": len(item.members)}

    preview_items = [row for row in (payload.get("items") or []) if isinstance(row, dict)]
    expected_sources = {
        _normalize_path(plugin, getattr(member, "path", ""))
        for member in item.members
        if getattr(member, "path", None)
    }
    by_source: Dict[str, dict] = {}
    for row in preview_items:
        source = _normalize_path(plugin, row.get("source"))
        if source:
            by_source[source] = row

    missing = sorted(source for source in expected_sources if source not in by_source)
    failed: List[str] = []
    empty_target: List[str] = []
    target_sources: Dict[str, List[str]] = defaultdict(list)

    for source in sorted(expected_sources):
        row = by_source.get(source)
        if not row:
            continue
        if not bool(row.get("success")):
            failed.append(source)
            continue
        target = _normalize_path(plugin, row.get("target"))
        if not target:
            empty_target.append(source)
            continue
        target_sources[target].append(source)

    duplicates = {
        target: sources
        for target, sources in target_sources.items()
        if len(set(sources)) > 1
    }

    details = {
        "expected": len(expected_sources),
        "preview_total": len(preview_items),
        "matched": len(expected_sources - set(missing)),
        "missing": missing[:20],
        "failed": failed[:20],
        "empty_target": empty_target[:20],
        "duplicate_targets": {
            target: sources[:10] for target, sources in list(duplicates.items())[:10]
        },
    }

    problems: List[str] = []
    if missing:
        problems.append(f"{len(missing)} 个源文件未进入 MoviePilot 预览")
    if failed:
        problems.append(f"{len(failed)} 个源文件预览失败")
    if empty_target:
        problems.append(f"{len(empty_target)} 个源文件没有目标路径")
    if duplicates:
        examples = []
        for target, sources in list(duplicates.items())[:3]:
            names = ", ".join(source.rsplit("/", 1)[-1] for source in sources[:4])
            examples.append(f"{names} -> {target}")
        problems.append(f"发现 {len(duplicates)} 组重复目标：" + "；".join(examples))

    if problems:
        return False, "；".join(problems), details

    episode_safe, episode_message, details = audit_episode_expectations(
        plugin,
        item,
        payload,
        details,
    )
    if not episode_safe:
        return False, episode_message, details
    return True, "", details'''
loss = replace_function(loss, "_audit_preview", new_audit)

new_build = r'''def _build_moviepilot_kwargs(plugin: Any, item: _FolderBatchEnvelope) -> Tuple[TransferChain, Any, Dict[str, Any], Optional[str]]:
    """显式构建唯一 Preview 上下文：MP 识别 → 集数适配 → MP 分类核验。"""
    directory_item = _directory_fileitem(plugin, item)
    transfer_chain = TransferChain()

    context, recognize_error = _moviepilot_directory_context(directory_item.path)
    media = getattr(context, "media_info", None) if context else None

    kwargs: Dict[str, Any] = {
        "fileitem": directory_item,
        "background": False,
        "manual": False,
    }
    if media:
        kwargs["mediainfo"] = media
        media_type = getattr(media, "type", None)
        if media_type:
            kwargs["mtype"] = media_type

    # v3.7.3：不再依赖 ContextVar/sample bridge 或 installer 链；整组成员直接进入 MP 推荐器。
    kwargs, episode_error, episode_note = apply_episode_name_adapter(
        plugin,
        item,
        transfer_chain,
        directory_item,
        kwargs,
    )
    if episode_error:
        return transfer_chain, directory_item, {}, episode_error

    # 分类事实必须晚于 episode TV 上下文收口，继续只使用 MoviePilot CategoryHelper。
    kwargs, category_error = apply_category_consistency(item, kwargs)
    if category_error:
        return transfer_chain, directory_item, kwargs, category_error

    media = kwargs.get("mediainfo")
    epformat = kwargs.get("epformat")
    if media:
        logger.info(
            "【光鸭云盘助手】【数据安全校验】MoviePilot 目录上下文: %s -> %s；分类=%s",
            item.path,
            getattr(media, "title_year", None) or getattr(media, "title", ""),
            getattr(media, "category", None) or "由 MoviePilot 决定",
        )
    elif recognize_error:
        logger.warning(
            "【光鸭云盘助手】【数据安全校验】%s；继续仅使用 MoviePilot 原生整理预览: %s",
            recognize_error,
            item.path,
        )
    if episode_note and not epformat:
        logger.debug(
            "【光鸭云盘助手】【数据安全校验】MoviePilot 未推荐额外集数模板: %s - %s",
            item.path,
            episode_note,
        )

    return transfer_chain, directory_item, kwargs, None'''
loss = replace_function(loss, "_build_moviepilot_kwargs", new_build)
loss_path.write_text(loss, encoding="utf-8")


# 4) Runtime candidate filter no longer installs recognition/preview behavior wrappers.
filter_path = PLUGIN / "organizer_candidate_filter.py"
filter_text = filter_path.read_text(encoding="utf-8")
for line in (
    "from .organizer_episode_name_adapter_v3411 import install_episode_name_adapter_v3411\n",
    "from .organizer_episode_sample_bridge_v3411 import install_episode_sample_bridge_v3411\n",
    "from .organizer_category_consistency_v3412 import install_category_consistency_v3412\n",
    "install_episode_name_adapter_v3411()\n",
    "install_episode_sample_bridge_v3411()\n",
    "install_category_consistency_v3412()\n",
):
    filter_text = filter_text.replace(line, "")
needle = "v3.7.2 起 loss guard 终态核对与 empty-folder 陈旧任务收口也由 Execution 显式负责，两个旧 installer 退出运行图。\n"
if needle not in filter_text:
    raise RuntimeError("candidate doc anchor missing")
filter_text = filter_text.replace(
    needle,
    needle + "v3.7.3 起集数整组样本/弱命名复核与分类一致性改为 loss guard 显式 Preview 上下文，不再串联三个 build/audit installer。\n",
)
filter_path.write_text(filter_text, encoding="utf-8")


# 5) ContextVar sample bridge is fully obsolete once member samples are passed explicitly.
sample_path = PLUGIN / "organizer_episode_sample_bridge_v3411.py"
if sample_path.exists():
    sample_path.unlink()


# 6) Behavioral tests bind to explicit ownership, not installer ordering.
(TESTS / "test_episode_name_adapter_v3411.py").write_text(r'''from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
ADAPTER = (PLUGIN / "organizer_episode_name_adapter_v3411.py").read_text(encoding="utf-8")
LOSS = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_adapter_tries_moviepilot_with_full_scanned_member_list_first():
    for token in (
        "recommend_episode_format(",
        "fileitem=directory_item",
        "fileitems=members",
        "MoviePilot 使用整组文件生成集数模板",
    ):
        assert token in ADAPTER, token


def test_adapter_covers_common_episode_name_families():
    for token in (
        "_SXE_RANGE", "_EP_RANGE", "_CN_EP", "_CN_REVERSE", "_CN_SUFFIX",
        "_HASH_EP", "_BRACKET_EP", "_TILDE_EP", "_LEADING_EP", "_ONLY_EP",
        "_TRAILING_EP", "01 4K", "EP01", "第01集",
    ):
        assert token in ADAPTER, token


def test_weak_names_require_multiple_unique_samples_and_mp_parser_validation():
    for token in (
        "len(tokens) < 2", "weak_single_sample", "weak_duplicate_episode",
        "FormatParser(eformat=template)", "_validated_expectations", "parsed_start != token.start",
    ):
        assert token in ADAPTER, token


def test_preview_rechecks_final_moviepilot_episode_before_real_move():
    for token in (
        "_guangya_episode_expectations_v3411", "actual_episode != expected_episode",
        "集号二次校验失败", "MoviePilot解析为E",
    ):
        assert token in ADAPTER, token
    assert "audit_episode_expectations(" in LOSS


def test_adapter_does_not_hardcode_media_identity_or_target_policy():
    for forbidden in (
        "tmdb_id=", "media_id=", "self._guangya_api.move", "self._guangya_api.copy",
        "DirectoryHelper().get_dir(", "get_rename_path(",
    ):
        assert forbidden not in ADAPTER, forbidden
    assert "_moviepilot_tv_context_from_directory_meta" in ADAPTER


def test_episode_compatibility_is_pure_helper_owned_by_loss_guard():
    assert "install_episode_name_adapter_v3411" not in ADAPTER
    assert "install_episode_name_adapter_v3411" not in FILTER
    assert "organizer_episode_sample_bridge_v3411" not in FILTER
    assert "from . import organizer_loss_guard_v349 as _loss_guard" not in ADAPTER
    assert "_build_moviepilot_kwargs =" not in ADAPTER
    assert "_audit_preview =" not in ADAPTER
    assert "apply_episode_name_adapter(" in LOSS
    assert "audit_episode_expectations(" in LOSS


def test_v3411_feature_remains_in_current_release():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v352.js?v={current}" in REMOTE
    assert package["history"]["v3.4.11"] == "增加多形态集号适配和整组校验，支持 01 4K、EP01、第01集等弱命名。"
''', encoding="utf-8")

(TESTS / "test_category_consistency_v3412.py").write_text(r'''from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
CATEGORY = (PLUGIN / "organizer_category_consistency_v3412.py").read_text(encoding="utf-8")
LOSS = (PLUGIN / "organizer_loss_guard_v349.py").read_text(encoding="utf-8")
FILTER = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
REMOTE = (PLUGIN / "dist" / "assets" / "remoteEntry.js").read_text(encoding="utf-8")


def test_category_reconciliation_uses_moviepilot_category_helper_only():
    for token in (
        "CategoryHelper", "get_tv_category", "get_movie_category", "tmdb_info",
        "deepcopy(media)", "corrected.category = expected", "origin_country",
        "original_language", "production_countries", "分类一致性",
    ):
        assert token in CATEGORY, token
    for forbidden in (
        'expected = "国产剧"', 'expected = "欧美剧"', 'expected = "日韩剧"',
        "DirectoryHelper().get_dir(", "self._guangya_api.move", "self._guangya_api.copy",
    ):
        assert forbidden not in CATEGORY, forbidden


def test_category_consistency_is_explicit_after_episode_context():
    assert "install_category_consistency_v3412" not in CATEGORY
    assert "install_category_consistency_v3412" not in FILTER
    assert "_build_moviepilot_kwargs =" not in CATEGORY
    assert "apply_category_consistency(" in LOSS
    assert LOSS.index("apply_episode_name_adapter(") < LOSS.index("apply_category_consistency(")


def test_category_verification_fails_closed_when_moviepilot_rules_cannot_be_checked():
    for token in (
        "识别结果缺少 TMDB 原始详情，无法核对 MoviePilot 分类规则",
        "MoviePilot CategoryHelper 分类核验异常", "已阻止真实整理",
        "return resolved, category_error",
    ):
        assert token in CATEGORY, token
    assert "if category_error:" in LOSS


def test_category_diagnostics_expose_moviepilot_facts():
    for token in (
        "MoviePilot 当前分类=%s", "origin_country=%s", "production_countries=%s",
        "original_language=%s", "识别上下文分类与 MoviePilot 当前 category.yaml 不一致",
    ):
        assert token in CATEGORY, token


def test_v3412_release_metadata_is_consistent():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["ShukGuangYaDisk"]
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    current = package["version"]
    assert local["version"] == current
    assert f'plugin_version = "{current}"' in ENTRY
    assert f"__federation_expose_AssistantPage-v352.js?v={current}" in REMOTE
    assert package["history"]["v3.4.12"] == "按 MoviePilot 当前 category.yaml 重新核验分类，修复缓存或外部识别源残留分类导致的错误目录。"
''', encoding="utf-8")

(TESTS / "test_organizer_phase2_v373_contract.py").write_text(r'''from pathlib import Path

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
    assert LOSS.index("apply_episode_name_adapter(") < LOSS.index("apply_category_consistency(")
    assert "MoviePilot 识别 → 集数适配 → MP 分类核验" in LOSS


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
''', encoding="utf-8")

print("v3.7.3 recognition/preview explicit-core migration applied")
