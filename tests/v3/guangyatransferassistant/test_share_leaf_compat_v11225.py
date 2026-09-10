from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PATCH = PLUGIN / "share_leaf_compat_v11225.py"
FAST = PLUGIN / "fast_recall_v1126.py"

text = PATCH.read_text(encoding="utf-8")
fast = FAST.read_text(encoding="utf-8")


def _load_helper():
    tree = ast.parse(text, filename=str(PATCH))
    names = {
        "_first_v11225",
        "_candidate_maps_v11225",
        "_safe_int_v11225",
        "_leaf_item_v11225",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=nodes, type_ignores=[])

    def safe_relative(value):
        raw = str(value or "").replace("\\", "/")
        parts = []
        for part in raw.split("/"):
            part = part.strip()
            if not part or part in {".", ".."}:
                continue
            parts.append(part)
        return "/".join(parts)

    namespace = {
        "Any": object,
        "Dict": dict,
        "List": list,
        "Optional": object,
        "_safe_relative_path": safe_relative,
        "_NAME_KEYS_V11225": (
            "fileName", "filename", "file_name", "name", "displayName", "display_name",
            "resourceName", "resource_name", "resName", "objectName", "object_name",
            "originalName", "original_name", "fullName", "full_name", "title",
        ),
        "_PATH_KEYS_V11225": ("relativePath", "relative_path", "filePath", "file_path", "fullPath", "full_path", "path"),
        "_ID_KEYS_V11225": ("fileId", "file_id", "id", "fid", "resId", "res_id", "resourceId", "resource_id", "objectId", "object_id"),
        "_EXT_KEYS_V11225": ("fileExt", "file_ext", "extension", "ext", "fileSuffix", "file_suffix", "suffix"),
        "_SIZE_KEYS_V11225": ("fileSize", "file_size", "size", "length", "contentLength", "content_length"),
        "_DIGEST_KEYS_V11225": ("sha1", "sha256", "md5", "hash", "etag"),
        "_NESTED_KEYS_V11225": ("fileInfo", "file_info", "resource", "resourceInfo", "resource_info", "item", "detail", "info"),
    }
    exec(compile(module, str(PATCH), "exec"), namespace)
    return namespace["_leaf_item_v11225"]


def test_v11225_files_parse_and_mro_is_wired_before_auto_recovery():
    ast.parse(text, filename=str(PATCH))
    ast.parse(fast, filename=str(FAST))
    assert "from .share_leaf_compat_v11225 import GuangYaShareLeafCompatV11225Mixin" in fast
    head = fast.split("class GuangYaFastRecallV1126Mixin(", 1)[1].split("):", 1)[0]
    assert head.index("GuangYaShareLeafCompatV11225Mixin") < head.index("GuangYaAutoRecoveryV11224Mixin")


def test_v11225_retry_request_includes_share_id_and_access_token():
    method = text.split("    def _inspect_share_with_share_id_v11225(", 1)[1].split("    def _inspect_share(", 1)[0]
    assert '"shareId": list_share_id' in method
    assert '"accessToken": token' in method
    assert '"parentId": parent_id' in method
    assert 'full_share_id.split("_", 1)[0]' in method


def test_v11225_only_retries_when_legacy_has_leafs_but_all_paths_are_empty():
    predicate = text.split("    def _probe_has_empty_leaf_paths_v11225(", 1)[1].split(
        "    def _inspect_share_with_share_id_v11225(", 1
    )[0]
    assert "if not files" in predicate
    assert "return bool(paths) and not any(paths)" in predicate
    inspect_method = text.split("    def _inspect_share(self, share_url", 1)[1]
    assert "super()._inspect_share(share_url)" in inspect_method
    assert "_probe_has_empty_leaf_paths_v11225" in inspect_method
    assert "分享叶子文件名读取异常" in inspect_method


def test_v11225_leaf_item_recovers_nested_filename_and_extension_fields():
    helper = _load_helper()
    row = helper({
        "fileId": "abc",
        "name": "/",
        "fileInfo": {
            "resourceName": "最后目击.2026.1080p",
            "fileExt": "mkv",
            "fileSize": "12345",
            "md5": "deadbeef",
        },
        "type": 1,
    })
    assert row is not None
    assert row["id"] == "abc"
    assert row["name"] == "最后目击.2026.1080p.mkv"
    assert row["size"] == 12345
    assert row["digest"] == "deadbeef"
    assert row["is_dir"] is False


def test_v11225_leaf_item_can_fall_back_to_path_when_name_is_placeholder():
    helper = _load_helper()
    row = helper({
        "resId": "f2",
        "name": "..",
        "fullPath": "/最后目击 (2026)/最后目击.2026.WEB-DL.mp4",
        "fileSize": 9,
        "fileType": "file",
    })
    assert row is not None
    assert row["name"] == "最后目击.2026.WEB-DL.mp4"
    assert row["path_hint_v11225"].endswith("最后目击.2026.WEB-DL.mp4")
