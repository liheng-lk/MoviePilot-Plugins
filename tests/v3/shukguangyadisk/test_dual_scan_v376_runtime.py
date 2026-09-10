from __future__ import annotations

import importlib.util
import sys
import time
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins.v3" / "shukguangyadisk" / "organizer_dual_scan_v376.py"


def load_runtime_module():
    package_name = f"_shuk_v376_{uuid.uuid4().hex}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(MODULE_PATH.parent)]

    app_module = types.ModuleType("app")
    sdk_module = types.ModuleType("app.sdk")
    logging_module = types.ModuleType("app.sdk.logging")
    logging_module.logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )

    models_module = types.ModuleType(f"{package_name}.models")

    class GuangYaOrganizerResponse:
        pass

    models_module.GuangYaOrganizerResponse = GuangYaOrganizerResponse

    organizer_module = types.ModuleType(f"{package_name}.organizer")

    class FakeBaseOrganizer:
        def get_organizer_api(self):
            return [{"path": "/organize/monitor/scan"}]

    organizer_module.GuangYaOrganizerMixin = FakeBaseOrganizer

    monitor_module = types.ModuleType(f"{package_name}.organizer_monitor_v366")

    class FakeMonitor:
        def __init__(self):
            self._organize_monitor_path = "/incoming"
            self._organize_monitor_enabled = True
            self._organize_monitor_interval = 60
            self._enabled = True
            self._guangya_api = object()
            self._v360_last_tick = 0.0
            self._organize_monitor_last_tick = 0.0
            self._data = {}
            self._status = {}
            self._cursor = {}
            self.responses = []
            self.baseline_marked = 0

        def init_organizer_monitor(self):
            return None

        @staticmethod
        def _v360_norm(value):
            text = str(value or "")
            return text.rstrip("/") or "/"

        @staticmethod
        def _v360_primary_files(files):
            return list(files or [])

        def _v360_schedule_resource(self, group_path, files):
            return {"scheduled": False, "reason": "fake", "phases": {}}

        def run_organize_monitor_scan(self, manual=False):
            if not self.responses:
                return {"success": True, "data": {"known_scan": True, "scheduled": False}}
            return self.responses.pop(0)

        def api_organize_monitor_status(self):
            return {"success": True, "data": {"status": dict(self._status)}}

        def get_data(self, key):
            return self._data.get(key)

        def save_data(self, key, value):
            self._data[key] = value

        def _save_monitor_status(self, **kwargs):
            self._status.update(kwargs)

        def _v360_load_cursor(self, root):
            return dict(self._cursor or {"cycle": 1})

        @staticmethod
        def _v360_new_cursor(root, *, cycle=1):
            return {"monitor_path": root, "cycle": cycle, "queue": [root], "remaining": 1}

        def _v360_save_cursor(self, cursor):
            self._cursor = dict(cursor)

        def _v366_mark_baseline_complete(self):
            self.baseline_marked += 1

    monitor_module.GuangYaOrganizerMonitorV366Mixin = FakeMonitor

    modules = {
        package_name: package,
        "app": app_module,
        "app.sdk": sdk_module,
        "app.sdk.logging": logging_module,
        f"{package_name}.models": models_module,
        f"{package_name}.organizer": organizer_module,
        f"{package_name}.organizer_monitor_v366": monitor_module,
    }

    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.organizer_dual_scan_v376",
            MODULE_PATH,
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.install_dual_scan_v376()
        return module, FakeMonitor, FakeBaseOrganizer


class DualScanV376RuntimeTest(unittest.TestCase):
    def test_full_session_keeps_cursor_progress_across_known_fast_path(self):
        module, FakeMonitor, _ = load_runtime_module()
        monitor = FakeMonitor()
        monitor.responses = [
            {
                "success": True,
                "data": {
                    "dirs_scanned": 5,
                    "files_seen": 10,
                    "resource_dirs": 1,
                    "remaining_dirs": 3,
                    "scheduled": False,
                },
            },
            {
                "success": True,
                "data": {
                    "known_scan": True,
                    "known_total": 8,
                    "known_checked": 8,
                    "known_changed": 1,
                    "scheduled": True,
                },
            },
            {
                "success": True,
                "data": {
                    "dirs_scanned": 3,
                    "files_seen": 6,
                    "resource_dirs": 1,
                    "remaining_dirs": 0,
                    "cycle_complete": True,
                    "scheduled": False,
                },
            },
        ]

        first = monitor._v376_start_full_scan("manual")
        self.assertTrue(first["data"]["full_scan_active"])
        self.assertEqual(first["data"]["full_scan_remaining_dirs"], 3)

        second = monitor._v376_run_full_scan_step("auto-resume")
        self.assertTrue(second["data"]["full_scan_active"])
        self.assertEqual(second["data"]["full_scan_remaining_dirs"], 3)

        final = monitor._v376_run_full_scan_step("auto-resume")
        self.assertFalse(final["data"]["full_scan_active"])
        self.assertEqual(final["data"]["full_scan_remaining_dirs"], 0)
        self.assertEqual(monitor.baseline_marked, 1)
        session = monitor.get_data(module._FULL_SESSION_KEY)
        self.assertFalse(session["active"])

    def test_manual_stop_suppresses_auto_but_manual_restart_still_works(self):
        module, FakeMonitor, _ = load_runtime_module()
        monitor = FakeMonitor()
        monitor.responses = [
            {
                "success": True,
                "data": {"dirs_scanned": 1, "remaining_dirs": 4, "scheduled": False},
            }
        ]
        monitor._v376_start_full_scan("manual")
        stopped = monitor._v376_stop_full_scan("manual")
        self.assertFalse(stopped["data"]["full_scan_active"])
        last = monitor.get_data(module._FULL_LAST_KEY)
        self.assertGreater(last["suppressed_until"], time.time())
        self.assertFalse(module._full_due(monitor))

        monitor.responses = [
            {
                "success": True,
                "data": {"dirs_scanned": 1, "remaining_dirs": 2, "scheduled": False},
            }
        ]
        restarted = monitor._v376_start_full_scan("manual")
        self.assertTrue(restarted["data"]["full_scan_active"])

    def test_status_and_api_projection_include_dual_scan_controls(self):
        _, FakeMonitor, FakeBaseOrganizer = load_runtime_module()
        monitor = FakeMonitor()
        status = monitor.api_organize_monitor_status()["data"]["status"]
        self.assertEqual(status["scan_engine"], "dual-channel-v3.7.6")
        self.assertEqual(status["log_stage_schema"], "1触发/2准备/3发现/4判定/5入队/6完成")
        self.assertEqual(status["log_filter_hint"], "【光鸭云盘助手】【整理】")

        base = FakeBaseOrganizer()
        paths = {row["path"] for row in base.get_organizer_api()}
        self.assertIn("/organize/monitor/incremental-scan", paths)
        self.assertIn("/organize/monitor/full-scan", paths)
        self.assertIn("/organize/monitor/full-scan/stop", paths)


if __name__ == "__main__":
    unittest.main()
