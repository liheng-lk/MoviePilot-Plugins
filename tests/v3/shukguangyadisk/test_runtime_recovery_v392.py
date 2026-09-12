from __future__ import annotations

import unittest

from source_helper import source_text


class RuntimeRecoveryV392ContractTest(unittest.TestCase):
    def test_qr_errors_are_not_swallowed(self):
        client = source_text("guangya_client.py")
        legacy = source_text("_plugin_legacy.py")
        self.assertIn("_auth_error_message", client)
        self.assertIn("treat_http_error_as_response=True", client)
        self.assertIn("_account_web_headers()", client)
        self.assertIn('"stage": "device_token_error"', client)
        self.assertIn('"stage": "device_code_error"', legacy)
        self.assertIn('"login_alternatives": ["sms", "token"]', legacy)

    def test_login_and_config_refresh_moviepilot_scheduler(self):
        entry = source_text("__init__.py")
        self.assertIn("def _refresh_host_services", entry)
        self.assertIn("from app.application.scheduling import update_plugin_job", entry)
        self.assertIn('update_plugin_job("ShukGuangYaDisk")', entry)
        self.assertGreaterEqual(entry.count("self._refresh_host_services()"), 2)

    def test_monitor_has_bootstrap_and_heartbeat_diagnostics(self):
        final = source_text("organizer_monitor_final_v390.py")
        self.assertIn("DateTrigger", final)
        self.assertIn('"ShukGuangYaDiskAutoMonitorBootstrap"', final)
        self.assertIn("heartbeat_last_at", final)
        self.assertIn('heartbeat_last_reason="running"', final)
        self.assertIn("history_scope_version", final)

    def test_moviepilot_history_is_scoped_to_current_guangya_source(self):
        orchestrator = source_text("organizer_orchestrator_v351.py")
        marker = "def record(self: Any, event: Any, success: bool) -> None:"
        self.assertIn(marker, orchestrator)
        block = orchestrator.split(marker, 1)[1].split("GuangYaRecognitionMixin._record_terminal_transfer = record", 1)[0]
        self.assertIn("_is_own_transfer_fileitem", block)
        self.assertIn("_is_monitored_path", block)
        self.assertLess(block.index("_is_own_transfer_fileitem"), block.index("original_record(self, event, success)"))
        self.assertLess(block.index("_is_monitored_path"), block.index("original_record(self, event, success)"))

    def test_missing_source_resource_can_reach_terminal_queue_cleanup(self):
        hardening = source_text("organizer_hardening_v369.py")
        watch = source_text("organizer_watch_pipeline_v380.py")
        missing = hardening.split("def list_directory(plugin: Any, path: str):", 1)[1].split("def run_monitor_scan", 1)[0]
        self.assertIn("if not current:", missing)
        self.assertIn("return [], []", missing)
        terminal = watch.split("def _queue_terminal", 1)[1].split("def _dispatch_one", 1)[0]
        self.assertIn("primary <= 0", terminal)
        dispatch = watch.split("def _dispatch_one", 1)[1].split("def install_watch_pipeline_v380", 1)[0]
        self.assertIn("rows.pop(path, None)", dispatch)


if __name__ == "__main__":
    unittest.main()
