from __future__ import annotations

import unittest

from source_helper import source_text


class RuntimeRecoveryV394ContractTest(unittest.TestCase):
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

    def test_worker_handoff_does_not_join_under_owner_lock(self):
        guard = source_text("organizer_worker_guard.py")
        claim = guard.split("def _claim_isolated_runtime", 1)[1].split("def _release_isolated_runtime", 1)[0]
        self.assertIn("worker.join(timeout=1.25)", claim)
        self.assertIn("current_owner = _runtime_owner()", claim)
        self.assertIn("旧实例交接完成，新实例已接管 Worker owner", claim)
        self.assertIn('"owner_running_path"', guard)
        self.assertIn('"owner_handoff_requested"', guard)
        # join 必须位于第一个 owner-lock 临界区之后，避免旧 worker finally 释放 owner 时锁互等。
        first_lock = claim.index("with _runtime_lock():")
        join = claim.index("worker.join(timeout=1.25)")
        second_lock = claim.index("with _runtime_lock():", first_lock + 1)
        self.assertLess(first_lock, join)
        self.assertLess(join, second_lock)

    def test_legacy_queue_cleanup_is_process_serialized(self):
        cleanup = source_text("organizer_legacy_queue_cleanup_v343.py")
        self.assertIn("_V362_PROCESS_LOCK_ATTR", cleanup)
        self.assertIn("_V362_PROCESS_STATE_ATTR", cleanup)
        self.assertIn("def _migration_runtime_lock", cleanup)
        self.assertIn("def _migration_runtime_state", cleanup)
        self.assertIn("with _migration_runtime_lock():", cleanup)
        self.assertIn('"v362_process_serialized": True', cleanup)
        self.assertIn('shared["scope"] = scope', cleanup)

    def test_dispatch_wait_reason_is_observable_and_manual_full_wakes_queue(self):
        final = source_text("organizer_monitor_final_v390.py")
        watch = source_text("organizer_watch_pipeline_v380.py")
        self.assertIn("def _v394_manual_full_with_dispatch", final)
        self.assertIn('self._v390_dispatch_one(trigger=f"{trigger}-full")', final)
        self.assertIn("resource_dispatch_last_reason", final)
        self.assertIn("resource_dispatch_wait_seconds", final)
        self.assertIn("【光鸭云盘助手】【监控】【调度等待】", final)
        self.assertIn('"reason": "handoff"', watch)
        self.assertIn('"owner_worker_alive"', watch)
        self.assertIn('"reason": "queue_wait"', watch)
        self.assertIn('"wait_seconds": wait_seconds', watch)

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
