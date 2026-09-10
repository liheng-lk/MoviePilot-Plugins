import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PATCH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_partial_revisit_v375.py"
CANDIDATE = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_candidate_filter.py"


def _load_patch(monkeypatch):
    package_name = "_shukguangya_v375_testpkg"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PATCH.parent)]
    monkeypatch.setitem(sys.modules, package_name, package)

    monitor_module = types.ModuleType(f"{package_name}.organizer_monitor_v366")

    class FakeMonitor:
        def __init__(self):
            self.pending = True
            self.registered_result = None
            self.status = {}

        def _v366_finish_schedule(self, group_path, files, result):
            if result.get("scheduled"):
                self.pending = False
            return result

        def _v361_register_pending(self, group_path, files, result):
            self.pending = True
            self.registered_result = dict(result)

        @staticmethod
        def _v360_norm(value):
            return str(value)

        def _save_monitor_status(self, **kwargs):
            self.status.update(kwargs)

    monitor_module.GuangYaOrganizerMonitorV366Mixin = FakeMonitor
    monkeypatch.setitem(
        sys.modules,
        f"{package_name}.organizer_monitor_v366",
        monitor_module,
    )

    app_module = types.ModuleType("app")
    sdk_module = types.ModuleType("app.sdk")
    logging_module = types.ModuleType("app.sdk.logging")
    logging_module.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "app", app_module)
    monkeypatch.setitem(sys.modules, "app.sdk", sdk_module)
    monkeypatch.setitem(sys.modules, "app.sdk.logging", logging_module)

    spec = importlib.util.spec_from_file_location(
        f"{package_name}.organizer_partial_revisit_v375",
        PATCH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module, FakeMonitor


def test_partial_success_re_registers_pending_for_waiting_siblings(monkeypatch):
    module, fake_monitor = _load_patch(monkeypatch)
    module.install_partial_revisit_v375()
    monitor = fake_monitor()

    result = monitor._v366_finish_schedule(
        "/电视剧/测试剧/Season 1",
        [f"E{episode:02d}.mkv" for episode in range(1, 11)],
        {
            "scheduled": True,
            "reason": "queued",
            "primary": 10,
            "submitted": 4,
            "phases": {"ready": 4, "stabilizing": 6},
        },
    )

    assert result["scheduled"] is True
    assert monitor.pending is True
    assert monitor.registered_result["scheduled"] is False
    assert monitor.registered_result["reason"] == "partial_wait"
    assert monitor.status["partial_revisit_pending"] == 6


def test_all_ready_success_removes_pending_without_revisit(monkeypatch):
    module, fake_monitor = _load_patch(monkeypatch)
    module.install_partial_revisit_v375()
    monitor = fake_monitor()

    monitor._v366_finish_schedule(
        "/电视剧/测试剧/Season 1",
        [f"E{episode:02d}.mkv" for episode in range(1, 11)],
        {
            "scheduled": True,
            "reason": "queued",
            "primary": 10,
            "submitted": 10,
            "phases": {"ready": 10},
        },
    )

    assert monitor.pending is False
    assert monitor.registered_result is None
    assert monitor.status == {}


def test_non_revisitable_phases_do_not_create_permanent_pending(monkeypatch):
    module, fake_monitor = _load_patch(monkeypatch)
    module.install_partial_revisit_v375()

    for phase in ("completed", "blocked", "ignored", "unknown"):
        monitor = fake_monitor()
        monitor._v366_finish_schedule(
            "/电视剧/测试剧/Season 1",
            ["E01.mkv", "E02.mkv"],
            {
                "scheduled": True,
                "reason": "queued",
                "primary": 2,
                "submitted": 1,
                "phases": {"ready": 1, phase: 1},
            },
        )
        assert monitor.pending is False
        assert monitor.registered_result is None


def test_partial_revisit_patch_is_installed_in_runtime_graph():
    source = CANDIDATE.read_text(encoding="utf-8")
    assert "from .organizer_partial_revisit_v375 import install_partial_revisit_v375" in source
    assert "install_partial_revisit_v375()" in source
