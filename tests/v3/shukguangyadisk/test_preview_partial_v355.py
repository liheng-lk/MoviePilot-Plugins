from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH = (PLUGIN / "organizer_preview_partial_v355.py").read_text(encoding="utf-8")
CANDIDATE = (PLUGIN / "organizer_candidate_filter.py").read_text(encoding="utf-8")
STATE = (PLUGIN / "organizer_state.py").read_text(encoding="utf-8")


def test_v355_only_rescues_folder_preview_missing_member_failures():
    for token in (
        '_MISSING_PREVIEW_TOKEN = "源文件未进入 MoviePilot 预览"',
        'if success or _MISSING_PREVIEW_TOKEN not in str(message or ""):',
        '_rescue_partial_preview(self, item)',
    ):
        assert token in PATCH, token


def test_v355_reuses_moviepilot_context_and_preview_for_each_member():
    for token in (
        '_loss_guard._build_moviepilot_kwargs(plugin, item)',
        'kwargs["fileitem"] = member',
        'kwargs["preview"] = True',
        'transfer_chain.do_transfer(**kwargs)',
        '_loss_guard._preview_result(result)',
    ):
        assert token in PATCH, token


def test_unpreviewable_member_uses_v370_policy_instead_of_one_generic_block():
    for token in (
        'should_probe_source_presence(reason)',
        'FileDisposition.LEAVE_UNRECOGNIZED',
        'mark_non_actionable',
        'FileDisposition.RETRY_TRANSIENT',
        'result="preview_member_isolated"',
    ):
        assert token in PATCH, token
    assert 'for name in ("stabilizing", "inflight", "retry"):' in STATE


def test_v355_keeps_target_uniqueness_guard_when_falling_back_to_per_member():
    for token in (
        'by_target: Dict[str, List[str]] = defaultdict(list)',
        'if len(set(sources)) > 1',
        'result="preview_target_conflict_isolated"',
        '逐文件补预览发现重复目标',
    ):
        assert token in PATCH, token


def test_safe_members_continue_through_moviepilot_real_transfer():
    for token in (
        '_conflict._execute_member(',
        'attempted += 1',
        '成员是否完成仍由 MP 最终事件/历史证据决定',
    ):
        assert token in PATCH, token


def test_v355_installs_after_v354_completion_evidence_layer():
    reconcile_pos = CANDIDATE.index('install_completion_reconcile_v354()')
    rescue_pos = CANDIDATE.index('install_preview_partial_v355()')
    assert rescue_pos > reconcile_pos
    assert 'from .organizer_preview_partial_v355 import install_preview_partial_v355' in CANDIDATE


def test_v355_has_runtime_diagnostic_log():
    for token in (
        '【v3.5.5】【预览局部补救】',
        '逐文件确认=%s',
        '实际整理=%s',
        '未识别保留=%s',
        '暂时失败=%s',
        '安全阻断=%s',
        '不再因单个缺员拖死整个资源',
    ):
        assert token in PATCH, token
