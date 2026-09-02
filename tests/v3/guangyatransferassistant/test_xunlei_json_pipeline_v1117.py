from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PIPELINE = PLUGIN / "xunlei_json_pipeline_v1117.py"
LOGGING = PLUGIN / "viewing_logging_v1113.py"

pipeline = PIPELINE.read_text(encoding="utf-8")
logging = LOGGING.read_text(encoding="utf-8")


def test_pipeline_parses_and_is_between_viewing_dispatch_and_integrity():
    ast.parse(pipeline, filename=str(PIPELINE))
    ast.parse(logging, filename=str(LOGGING))
    assert "from .xunlei_json_pipeline_v1117 import GuangYaXunleiJsonPipelineV1117Mixin" in logging
    assert "GuangYaViewingDispatchV1113Mixin,\n    GuangYaXunleiJsonPipelineV1117Mixin,\n    GuangYaXunleiIntegrityV1116Mixin," in logging
    assert 'build_id = "20260902-r30"' in logging


def test_stage_a_keeps_user_script_json_contract():
    make_json = pipeline.split("    def _xunlei_make_json_v1117(", 1)[1].split(
        "    # ------------------------------------------------------------------\n    # Stage B", 1
    )[0]
    for marker in (
        '"sourceXunlei": True',
        '"sourceTag": "xunlei"',
        '"shareId"',
        '"passCodeToken"',
        '"gcid"',
        '"md5"',
        '"cid"',
        '"tripleCid"',
        '"wholeCid"',
        '"downloadUrl"',
        '"fileId"',
        '"parentId"',
    ):
        assert marker in make_json
    assert '"scriptVersion": "1.1.3"' in make_json
    assert '"scriptAuthor": "sumuve"' in make_json
    assert "1.1.3-mp-compatible" not in make_json


def test_share_rows_are_annotated_before_import_even_when_file_info_is_skipped():
    share_files = pipeline.split("    def _xunlei_share_files(", 1)[1].split(
        "    def _xunlei_post_json_v1117(", 1
    )[0]
    assert 'row["shareId"]' in share_files
    assert 'row["passCodeToken"]' in share_files
    assert 'row["sourceXunlei"] = True' in share_files
    assert 'row["sourceTag"] = "xunlei"' in share_files


def test_file_info_keeps_stable_script_fast_path_and_post_download_fallbacks():
    info = pipeline.split("    def _xunlei_file_info(", 1)[1].split(
        "    @staticmethod\n    def _xunlei_format_size_v1117", 1
    )[0]
    assert "super()._xunlei_file_info" in info
    assert '"/drive/v1/share/detail"' in info
    assert '"/drive/v1/share/download"' in info
    assert '"/drive/v1/share/files/download"' in info
    assert 'f"/drive/v1/files/{file_id}"' in info
    assert '"/drive/v1/share/save"' in info
    assert 'f"/drive/v1/tasks/{task_id}"' in info
    assert "_pick_download_url(body)" in info


def test_stage_b_matches_capacity2_probe_order_without_ordinary_upload():
    importer = pipeline.split("    def _xunlei_import_json_file_v1117(", 1)[1].split(
        "    def _rapid_transfer_xunlei_file(", 1
    )[0]
    assert '"capacity": 2' in importer
    assert '"capacity": 1' not in importer
    assert "OSS" in importer
    assert "get_res_center_token" in importer
    assert "check_can_flash_upload" in importer
    assert "cid_values" in importer
    assert "md5_combos" in importer


def test_download_url_recomputes_real_three_sample_cid_on_import():
    importer = pipeline.split("    def _xunlei_import_json_file_v1117(", 1)[1].split(
        "    def _rapid_transfer_xunlei_file(", 1
    )[0]
    assert "_xunlei_compute_triple_cid(download_url, size)" in importer
    assert "triple.lower()" in importer
    assert "triple.upper()" in importer


def test_runtime_logs_explicit_json_generation_then_import():
    transfer = pipeline.split("    def _rapid_transfer_xunlei_file(", 1)[1]
    assert "_xunlei_make_json_v1117([row])" in transfer
    assert "【迅雷JSON】模板已生成" in transfer
    assert "按光鸭 importMd5Json 合同导入" in transfer
    assert "_xunlei_import_json_file_v1117" in transfer
