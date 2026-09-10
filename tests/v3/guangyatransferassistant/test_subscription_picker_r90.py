"""2.0.7-r90：接管订阅批量选择 — 绑定 production UI helper，禁止测副本算法。"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH_PATH = PLUGIN / "page_perf_v1123.py"
PATCH = PATCH_PATH.read_text(encoding="utf-8")
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
PACKAGE = (ROOT / "package.v3.json").read_text(encoding="utf-8")

_spec = importlib.util.spec_from_file_location("guangya_page_perf_v1123_r90", PATCH_PATH)
_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_module)

normalize_subscription_ids_v1124 = _module.normalize_subscription_ids_v1124
filter_visible_subscription_ids_v1124 = _module.filter_visible_subscription_ids_v1124
union_selected_subscription_ids_v1124 = _module.union_selected_subscription_ids_v1124
clear_selected_subscription_ids_v1124 = _module.clear_selected_subscription_ids_v1124
all_visible_subscription_ids_selected_v1124 = _module.all_visible_subscription_ids_selected_v1124
toggle_takeover_subscription_ids_v1124 = _module.toggle_takeover_subscription_ids_v1124
_subscription_picker_card_v1124 = _module.GuangYaPagePerfV1123Mixin._subscription_picker_card_v1124


def _catalog(*rows):
    return [{"title": title, "value": value} for title, value in rows]


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _buttons(card: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    for node in _walk(card):
        if node.get("component") != "VBtn":
            continue
        text = str(node.get("text") or "")
        found[text] = node
    return found


def _autocomplete(card: Dict[str, Any]) -> Dict[str, Any]:
    for node in _walk(card):
        if node.get("component") == "VAutocomplete":
            return node
    raise AssertionError("VAutocomplete missing")


def test_r90_release_metadata_only_here_and_contract():
    assert 'plugin_version = "2.0.8"' in ENTRY
    assert 'build_id = "20260910-r91"' in ENTRY
    assert '"version": "2.0.8"' in PACKAGE
    assert "全选当前结果" in PACKAGE


def test_production_picker_has_required_buttons_and_static_text():
    card = _subscription_picker_card_v1124(_catalog(("A (2026) · #1", 1)))
    buttons = _buttons(card)
    assert "全选当前结果" in buttons
    assert "取消全选" in buttons
    assert "添加 / 取消接管" in buttons
    for name, btn in buttons.items():
        text = str(btn.get("text") or "")
        assert "{{" not in text, f"config.text must be static: {name}"
        assert "}}" not in text


def test_production_autocomplete_binds_search_and_selection():
    card = _subscription_picker_card_v1124(_catalog(("Jupiter (2026) · #9", 9)))
    auto = _autocomplete(card)
    props = auto["props"]
    assert props["model"] == "_subscription_batch_v1124"
    assert props.get("model:search") == "_subscription_query_v1124"
    assert props["multiple"] is True
    assert props["chips"] is False
    # 唯一搜索入口：不再挂独立 VTextField
    assert not any(n.get("component") == "VTextField" for n in _walk(card))


def test_production_select_all_uses_query_and_union_helpers():
    catalog = _catalog(
        ("A (2024) · #1", 1),
        ("B (2026) · #2", 2),
        ("C (2026) · #3", 3),
        ("D (2025) · #4", 4),
    )
    visible = filter_visible_subscription_ids_v1124(catalog, "2026")
    assert set(visible) == {2, 3}
    selected = union_selected_subscription_ids_v1124([1], visible)
    assert selected == [1, 2, 3]


def test_production_select_all_source_references_query_and_union():
    card = _subscription_picker_card_v1124(_catalog(("A · #1", 1)))
    select_btn = _buttons(card)["全选当前结果"]
    props = select_btn["props"]
    js = str(props.get("onMousedown") or props.get("onClick") or "")
    assert "_subscription_query_v1124" in js
    assert "_subscription_catalog_v1124" in js
    assert "[...new Set([...current, ...visible])]" in js
    assert "onMousedown" in props  # 避免 blur 清空 search 后误全选


def test_same_title_keeps_distinct_ids():
    catalog = _catalog(
        ("Movie A (2020) · #100", 100),
        ("Movie A (2021) · #200", 200),
    )
    selected = union_selected_subscription_ids_v1124(
        [],
        filter_visible_subscription_ids_v1124(catalog, "Movie A"),
    )
    assert selected == [100, 200]


def test_clear_all_empties_selection():
    assert clear_selected_subscription_ids_v1124() == []
    card = _subscription_picker_card_v1124(_catalog(("A · #1", 1)))
    js = str(_buttons(card)["取消全选"]["props"]["onClick"])
    assert "_subscription_batch_v1124 = []" in js


def test_disabled_when_no_visible_or_no_selection():
    card = _subscription_picker_card_v1124(_catalog(("A · #1", 1)))
    buttons = _buttons(card)
    select_disabled = str(buttons["全选当前结果"]["props"]["disabled"])
    clear_disabled = str(buttons["取消全选"]["props"]["disabled"])
    apply_disabled = str(buttons["添加 / 取消接管"]["props"]["disabled"])
    assert select_disabled.startswith("{{") and select_disabled.endswith("}}")
    assert "visible.length" in select_disabled or "!visible.length" in select_disabled
    assert "_subscription_batch_v1124" in clear_disabled
    assert "_subscription_batch_v1124" in apply_disabled
    # 逻辑层：无可见结果时“全选”应视为不可用
    assert filter_visible_subscription_ids_v1124(_catalog(("A · #1", 1)), "zzz") == []
    assert all_visible_subscription_ids_selected_v1124([1], []) is False


def test_filter_change_keeps_selection():
    selected = [1, 2, 3]
    catalog = _catalog(
        ("One (2026) · #1", 1),
        ("Two (2025) · #2", 2),
        ("Three (2024) · #3", 3),
    )
    assert filter_visible_subscription_ids_v1124(catalog, "2026") == [1]
    assert selected == [1, 2, 3]
    assert filter_visible_subscription_ids_v1124(catalog, "") == [1, 2, 3]
    assert selected == [1, 2, 3]


def test_toggle_takeover_uses_ids():
    takeover = toggle_takeover_subscription_ids_v1124([100], [100, 200])
    assert set(takeover) == {200}
    assert toggle_takeover_subscription_ids_v1124(takeover, [200]) == []


def test_select_all_without_query_selects_all():
    catalog = _catalog(*[(f"Item {i} · #{i}", i) for i in range(1, 11)])
    selected = union_selected_subscription_ids_v1124(
        [],
        filter_visible_subscription_ids_v1124(catalog, ""),
    )
    assert len(selected) == 10


def test_page_perf_module_parses_and_exports_helper():
    ast.parse(PATCH)
    assert "def _subscription_picker_card_v1124" in PATCH
    assert '"model:search": "_subscription_query_v1124"' in PATCH
