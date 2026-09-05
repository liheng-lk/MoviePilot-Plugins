from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "shukguangyadisk"
SOURCE_PATH = PLUGIN / "organizer_source_terminal_v3618.py"
EXEC_PATH = PLUGIN / "organizer_execution_v360.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
EXEC = EXEC_PATH.read_text(encoding="utf-8")


def _load_module():
    app = sys.modules.setdefault("app", types.ModuleType("app"))
    sdk = sys.modules.setdefault("app.sdk", types.ModuleType("app.sdk"))
    logging_mod = types.ModuleType("app.sdk.logging")

    class _Logger:
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

    logging_mod.logger = _Logger()
    sys.modules["app.sdk.logging"] = logging_mod
    setattr(app, "sdk", sdk)
    setattr(sdk, "logging", logging_mod)

    spec = importlib.util.spec_from_file_location("shuk_v3618_source_terminal_test", SOURCE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Store:
    def __init__(self):
        self.state = {
            "completed": {},
            "ignored": {},
            "blocked": {},
            "stabilizing": {},
            "inflight": {},
            "retry": {},
        }

    def mutate(self, callback):
        return callback(self.state)


class _Item:
    def __init__(self, path: str):
        self.path = path


class _Api:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.paths = []

    def refresh_item(self, path):
        self.paths.append(str(path))
        if self.error:
            raise self.error
        return self.result


class _Plugin:
    def __init__(self, api):
        self._guangya_api = api
        self.store = _Store()
        self.pruned = 0

    @staticmethod
    def _v360_norm(path):
        text = str(path).replace("\\", "/")
        return text.rstrip("/") or "/"

    def _state(self):
        return self.store

    def _v361_prune_stale_pending(self):
        self.pruned += 1
        return 0


def test_v3618_sources_parse():
    ast.parse(SOURCE)
    ast.parse(EXEC)


def test_v3618_remote_fact_is_three_state_and_network_error_is_unknown():
    module = _load_module()
    missing = _Plugin(_Api(result=None))
    assert module.probe_source_presence_v3618(missing, _Item("/root/a.mkv")) == module.SourcePresence.MISSING
    assert module.confirm_source_missing_v3618(missing, _Item("/root/a.mkv")) is True
    assert missing._guangya_api.paths == ["/root/a.mkv", "/root/a.mkv"]

    present = _Plugin(_Api(result=object()))
    assert module.probe_source_presence_v3618(present, _Item("/root/a.mkv")) == module.SourcePresence.PRESENT
    assert module.confirm_source_missing_v3618(present, _Item("/root/a.mkv")) is False

    failed = _Plugin(_Api(error=RuntimeError("network down")))
    assert module.probe_source_presence_v3618(failed, _Item("/root/a.mkv")) == module.SourcePresence.UNKNOWN
    assert module.confirm_source_missing_v3618(failed, _Item("/root/a.mkv")) is False


def test_v3618_exact_retire_removes_only_missing_member_and_never_creates_retry():
    module = _load_module()
    plugin = _Plugin(_Api())
    target = "/root/show/E01.mkv"
    sibling = "/root/show/E02.mkv"
    for name in ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry"):
        plugin.store.state[name][target] = {"fingerprint": "a"} if name not in {"completed", "ignored"} else "a"
        plugin.store.state[name][sibling] = {"fingerprint": "b"} if name not in {"completed", "ignored"} else "b"

    removed = module.retire_missing_source_v3618(plugin, _Item(target))
    assert sum(removed.values()) == 6
    for name in ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry"):
        assert target not in plugin.store.state[name]
        assert sibling in plugin.store.state[name]
    assert plugin.pruned == 1


def test_v3618_directory_retire_removes_only_confirmed_missing_subtree():
    module = _load_module()
    plugin = _Plugin(_Api())
    plugin.store.state["retry"] = {
        "/root/show/E01.mkv": {"fingerprint": "1"},
        "/root/show/sub/E02.mkv": {"fingerprint": "2"},
        "/root/other/E01.mkv": {"fingerprint": "3"},
    }
    removed = module.retire_missing_source_v3618(plugin, _Item("/root/show"), subtree=True)
    assert removed["retry"] == 2
    assert list(plugin.store.state["retry"]) == ["/root/other/E01.mkv"]


def test_v3618_failure_text_is_only_a_probe_hint_not_absence_evidence():
    module = _load_module()
    assert module.source_missing_hint_v3618("E01.mkv 没有找到可整理的媒体文件") is True
    assert module.source_missing_hint_v3618("TMDB 识别失败") is False
    plugin = _Plugin(_Api(result=object()))
    assert module.probe_source_presence_v3618(plugin, _Item("/root/E01.mkv")) == module.SourcePresence.PRESENT
    assert module.confirm_source_missing_v3618(plugin, _Item("/root/E01.mkv")) is False


def test_v3618_execution_preflights_before_moviepilot_and_policy_rechecks_race():
    assert "confirm_source_missing_v3618(self, item)" in EXEC
    first_guard = EXEC.index("if confirm_source_missing_v3618(self, item):")
    first_super = EXEC.index("return super()._execute_isolated_transfer(item)", first_guard)
    assert first_guard < first_super
    fallback_start = EXEC.index("def _fallback_terminal_state")
    fallback = EXEC[fallback_start:EXEC.index("def api_organize_monitor_status", fallback_start)]
    assert "should_probe_source_presence(message)" in fallback
    assert "probe_source_presence_v3618(self, item)" in fallback
    assert "decide_failed_execution(message, presence)" in fallback
    assert "FileDisposition.RETIRE_MISSING" in fallback
    assert "FileDisposition.LEAVE_UNRECOGNIZED" in fallback
    assert "retire_missing_source_v3618" in fallback
    assert "mark_non_actionable" in fallback
    assert "mark_failed" not in fallback


def test_v3618_uses_refresh_item_to_bypass_stale_path_cache():
    assert "refresh_item" in SOURCE
    probe = SOURCE[SOURCE.index("def probe_source_presence_v3618"):SOURCE.index("def confirm_source_missing_v3618")]
    assert "refresh_item" in probe
    assert "get_item(" not in probe
    assert "except Exception" in probe
    assert "SourcePresence.UNKNOWN" in probe
    assert "SourcePresence.MISSING" in probe
    assert "SourcePresence.PRESENT" in probe
