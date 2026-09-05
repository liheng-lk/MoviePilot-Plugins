from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
PATCH_PATH = PLUGIN / "organizer_terminal_event_scope_v3620.py"
EXEC_PATH = PLUGIN / "organizer_execution_v360.py"
PATCH = PATCH_PATH.read_text(encoding="utf-8")
EXEC = EXEC_PATH.read_text(encoding="utf-8")


def _load_module():
    app = sys.modules.setdefault("app", types.ModuleType("app"))
    sdk = sys.modules.setdefault("app.sdk", types.ModuleType("app.sdk"))
    logging_mod = types.ModuleType("app.sdk.logging")

    class _Logger:
        def info(self, *args, **kwargs):
            pass

    logging_mod.logger = _Logger()
    sys.modules["app.sdk.logging"] = logging_mod
    setattr(app, "sdk", sdk)
    setattr(sdk, "logging", logging_mod)

    package_name = "shuk_v3620_scope_testpkg"
    package = types.ModuleType(package_name)
    package.__path__ = []
    sys.modules[package_name] = package

    pending_mod = types.ModuleType(f"{package_name}.organizer_pending_revisit_v361")
    recognition_mod = types.ModuleType(f"{package_name}.organizer_recognition")

    class _Pending:
        def _record_terminal_transfer(self, event, success):
            self.pending_calls += 1

    class _Recognition:
        def _record_terminal_transfer(self, event, success):
            self.recognition_calls += 1

    pending_mod.GuangYaOrganizerPendingRevisitV361Mixin = _Pending
    recognition_mod.GuangYaOrganizerMixin = _Recognition
    sys.modules[pending_mod.__name__] = pending_mod
    sys.modules[recognition_mod.__name__] = recognition_mod

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.organizer_terminal_event_scope_v3620",
        PATCH_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, _Pending, _Recognition


class _FileItem:
    def __init__(self, storage: str, path: str):
        self.storage = storage
        self.path = path


class _Event:
    def __init__(self, fileitem=None, history_id=1):
        self.event_data = {
            "fileitem": fileitem,
            "transfer_history_id": history_id,
        }


class _Plugin:
    def __init__(self):
        self.pending_calls = 0
        self.recognition_calls = 0

    @staticmethod
    def _event_payload(event):
        return event.event_data

    @staticmethod
    def _is_own_transfer_fileitem(fileitem):
        return str(getattr(fileitem, "storage", "")) in {"光鸭云盘助手", "Shuk-光鸭云盘"}

    @staticmethod
    def _is_monitored_path(path):
        path = str(path or "").replace("\\", "/")
        return path == "/光鸭媒体库" or path.startswith("/光鸭媒体库/")


def test_v3620_sources_parse_and_runtime_reports_current_hardening():
    ast.parse(PATCH, filename=str(PATCH_PATH))
    ast.parse(EXEC, filename=str(EXEC_PATH))
    assert '"runtime_hardening": "v3.6.20"' in EXEC


def test_real_115_strm_terminal_event_is_rejected_before_any_guangya_side_effect():
    module, pending_cls, recognition_cls = _load_module()
    module.install_terminal_event_scope_v3620()
    plugin = _Plugin()
    event = _Event(
        _FileItem(
            "local",
            "/video/115网盘/整理好/国产剧/逐玉 (2026)/Season 1/逐玉 - S01E28 - 第28集 - 2160p.strm",
        ),
        history_id=67659,
    )

    assert module.terminal_event_owned_v3620(plugin, event) is False
    pending_cls._record_terminal_transfer(plugin, event, True)
    recognition_cls._record_terminal_transfer(plugin, event, True)
    assert plugin.pending_calls == 0
    assert plugin.recognition_calls == 0


def test_other_storage_even_under_similar_path_is_rejected():
    module, pending_cls, recognition_cls = _load_module()
    module.install_terminal_event_scope_v3620()
    plugin = _Plugin()
    event = _Event(_FileItem("115", "/光鸭媒体库/剧集/伪装路径/E01.strm"), history_id=9)

    pending_cls._record_terminal_transfer(plugin, event, True)
    recognition_cls._record_terminal_transfer(plugin, event, False)
    assert plugin.pending_calls == 0
    assert plugin.recognition_calls == 0


def test_guangya_storage_outside_monitor_root_is_rejected():
    module, pending_cls, recognition_cls = _load_module()
    module.install_terminal_event_scope_v3620()
    plugin = _Plugin()
    event = _Event(_FileItem("光鸭云盘助手", "/其它目录/E01.mkv"), history_id=10)

    pending_cls._record_terminal_transfer(plugin, event, True)
    recognition_cls._record_terminal_transfer(plugin, event, True)
    assert plugin.pending_calls == 0
    assert plugin.recognition_calls == 0


def test_owned_guangya_terminal_event_still_reaches_existing_history_and_pending_chain():
    module, pending_cls, recognition_cls = _load_module()
    module.install_terminal_event_scope_v3620()
    plugin = _Plugin()
    event = _Event(
        _FileItem("光鸭云盘助手", "/光鸭媒体库/剧集/死人公司 (2024)/Season 3/E01.mp4"),
        history_id=72062,
    )

    assert module.terminal_event_owned_v3620(plugin, event) is True
    pending_cls._record_terminal_transfer(plugin, event, True)
    recognition_cls._record_terminal_transfer(plugin, event, True)
    assert plugin.pending_calls == 1
    assert plugin.recognition_calls == 1


def test_missing_fileitem_or_ownership_helpers_fail_closed():
    module, _, _ = _load_module()
    plugin = _Plugin()
    assert module.terminal_event_owned_v3620(plugin, _Event(None)) is False

    plugin._is_own_transfer_fileitem = None
    assert module.terminal_event_owned_v3620(
        plugin,
        _Event(_FileItem("光鸭云盘助手", "/光鸭媒体库/剧集/a.mkv")),
    ) is False


def test_v3620_wraps_both_history_and_pending_after_existing_runtime_layers():
    init = EXEC[EXEC.index("def init_organizer_monitor"):EXEC.index("def _execute_isolated_transfer")]
    fairness = "install_pending_fairness_v3615()"
    scope = "install_terminal_event_scope_v3620()"
    move = "install_move_confirmation_v360()"
    assert "from .organizer_terminal_event_scope_v3620 import install_terminal_event_scope_v3620" in init
    assert init.index(fairness) < init.index(scope) < init.index(move)
    assert "GuangYaRecognitionMixin._record_terminal_transfer = scoped_recognition_record" in PATCH
    assert "GuangYaOrganizerPendingRevisitV361Mixin._record_terminal_transfer = scoped_pending_record" in PATCH


def test_v3620_is_event_scope_only_not_media_or_file_policy():
    lower = PATCH.lower()
    for forbidden in (
        "recognize_media",
        "tmdb",
        "category",
        "move_item",
        "delete_file",
        "transferpendingoper",
        "request_retry",
    ):
        assert forbidden not in lower
    assert "_is_own_transfer_fileitem" in PATCH
    assert "_is_monitored_path" in PATCH
