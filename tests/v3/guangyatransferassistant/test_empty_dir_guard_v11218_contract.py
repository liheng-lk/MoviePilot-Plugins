from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
GUARD = PLUGIN / "empty_dir_guard_v11218.py"
MULTI = PLUGIN / "multisource_v180.py"
XUNLEI = PLUGIN / "xunlei_json_pipeline_v1117.py"


def test_v11218_guard_is_syntax_valid_and_does_not_add_downloader_route():
    text = GUARD.read_text(encoding="utf-8")
    ast.parse(text, filename=str(GUARD))
    lowered = text.lower()
    assert "moviepilot downloader" not in lowered
    assert "qbittorrent" not in lowered
    assert "transmission" not in lowered
    assert "/cloudcollection/v1/create_task" in MULTI.read_text(encoding="utf-8")


def test_v11218_cleanup_is_limited_to_this_attempt_empty_directories():
    text = GUARD.read_text(encoding="utf-8")
    assert '"created_candidates": set()' in text
    assert "if folder is None:" in text
    assert "children = list(list_dir(folder) or [])" in text
    assert "if children:" in text
    assert "if bool(delete(folder))" in text
    assert 'if path in {"/", protected}:' in text
    assert "if bool(txn.get(\"unsafe\"))" in text


def test_v11218_server_tasks_and_pending_verification_are_fail_closed():
    text = GUARD.read_text(encoding="utf-8")
    assert "_result_has_task_v11218" in text
    assert 'not bool(result.get("pending_verification"))' in text
    assert "not self._result_has_task_v11218(result)" in text


def test_v11218_pending_verification_uses_read_only_get_item_not_get_folder():
    tree = ast.parse(GUARD.read_text(encoding="utf-8"), filename=str(GUARD))
    verify = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_verify_restored_items"
    )
    calls = []
    for node in ast.walk(verify):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
    assert "get_item" in calls
    assert "get_folder" not in calls


def test_v11218_does_not_rewrite_xunlei_json_or_existing_missing_episode_fences():
    text = GUARD.read_text(encoding="utf-8")
    assert "scriptVersion" not in text
    assert "assess_media_identity" not in text
    assert "_authoritative_missing_v11214" not in text
    assert "_xunlei_authoritative_target_v11213" not in text
    assert "_xunlei_import_json_file_v1117" in text
    assert "scriptVersion" in XUNLEI.read_text(encoding="utf-8")
