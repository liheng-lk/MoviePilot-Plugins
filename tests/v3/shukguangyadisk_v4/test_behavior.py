"""光鸭云盘助手 V4 运行态行为测试。"""

from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import Future
from types import SimpleNamespace

from app.plugins.shukguangyadisk import GuangYaOrganizerV4, ShukGuangYaDisk


class OrganizerV4BehaviorTest(unittest.TestCase):
    """验证 V4 调度状态机的关键不变量。"""

    def new_organizer(self):
        """构造不触发 MoviePilot 插件数据库初始化的 Organizer 对象。"""
        return object.__new__(GuangYaOrganizerV4)

    def test_plugin_entry_imports_from_real_moviepilot(self):
        """真实 MoviePilot 包必须能导入最终插件类。"""
        self.assertEqual(ShukGuangYaDisk.plugin_version, "4.0.0-alpha1")
        self.assertTrue(issubclass(ShukGuangYaDisk, GuangYaOrganizerV4))
        self.assertTrue(callable(getattr(ShukGuangYaDisk, "get_api", None)))
        self.assertTrue(callable(getattr(ShukGuangYaDisk, "get_service", None)))

    def test_ready_task_is_not_starved_by_stabilizing_head(self):
        """队头仍稳定时，后续 READY 任务必须在同一次选择中被取出。"""
        organizer = self.new_organizer()
        tasks = {
            "/A.mkv": {
                "path": "/A.mkv",
                "state": "STABILIZING",
                "first_seen": 1,
                "next_run": 0,
            },
            "/B.mkv": {
                "path": "/B.mkv",
                "state": "READY",
                "first_seen": 2,
                "next_run": 0,
            },
        }
        organizer._organizer_tasks = lambda: tasks
        selected = organizer._organizer_next_task()
        self.assertIsNotNone(selected)
        self.assertEqual(selected["path"], "/B.mkv")

    def test_retry_wait_does_not_starve_later_ready_task(self):
        """未到期 RETRY 不能阻塞后面的 READY。"""
        organizer = self.new_organizer()
        tasks = {
            "/retry.mkv": {
                "path": "/retry.mkv",
                "state": "RETRY",
                "first_seen": 1,
                "next_run": time.time() + 3600,
            },
            "/ready.mkv": {
                "path": "/ready.mkv",
                "state": "READY",
                "first_seen": 2,
                "next_run": 0,
            },
        }
        organizer._organizer_tasks = lambda: tasks
        selected = organizer._organizer_next_task()
        self.assertEqual(selected["path"], "/ready.mkv")

    def test_old_remote_file_can_be_ready_on_first_observation(self):
        """首次发现的旧远端文件不应被人为再等待完整稳定窗口。"""
        organizer = self.new_organizer()
        organizer._organizer_stability = 30
        organizer._disk_name = "光鸭云盘助手"
        tasks = {}
        organizer._organizer_tasks = lambda: tasks
        organizer._organizer_save_tasks = lambda value: tasks.update(value)
        item = SimpleNamespace(
            path="/剧集/Season 1/E03.mkv",
            name="E03.mkv",
            type="file",
            fileid="f03",
            size=123,
            modify_time=time.time() - 120,
        )
        organizer._organizer_observe(item, "/剧集/Season 1")
        self.assertEqual(tasks[item.path]["state"], "READY")

    def test_fingerprint_change_restarts_stability_window(self):
        """同路径文件版本变化时必须重新进入 STABILIZING。"""
        organizer = self.new_organizer()
        organizer._organizer_stability = 30
        organizer._disk_name = "光鸭云盘助手"
        now = time.time()
        tasks = {
            "/movie.mkv": {
                "path": "/movie.mkv",
                "state": "COMPLETED",
                "fingerprint": "old|100|1",
                "first_seen": now - 500,
                "stable_since": now - 500,
                "attempts": 2,
            }
        }
        organizer._organizer_tasks = lambda: tasks
        organizer._organizer_save_tasks = lambda value: tasks.update(value)
        item = SimpleNamespace(
            path="/movie.mkv",
            name="movie.mkv",
            type="file",
            fileid="new",
            size=200,
            modify_time=now - 120,
        )
        organizer._organizer_observe(item, "/")
        self.assertEqual(tasks[item.path]["state"], "STABILIZING")
        self.assertGreaterEqual(tasks[item.path]["stable_since"], now)

    def test_preview_blocks_two_sources_to_same_target(self):
        """MoviePilot 预览出现多源同目标时必须阻止真实 move。"""
        ok, message = GuangYaOrganizerV4._organizer_preview_audit(
            "/src/A.mkv",
            {
                "items": [
                    {"source": "/src/A.mkv", "target": "/lib/X.mkv", "success": True},
                    {"source": "/src/B.mkv", "target": "/lib/X.mkv", "success": True},
                ]
            },
        )
        self.assertFalse(ok)
        self.assertIn("同一目标", message)

    def test_verifying_mode_never_executes_transfer_again(self):
        """VERIFYING 任务只能查历史，不能再次执行整理。"""
        organizer = self.new_organizer()
        calls = {"verify": 0, "execute": 0}

        def verify(task):
            calls["verify"] += 1
            return {"state": "COMPLETED", "message": "ok"}

        def execute(task):
            calls["execute"] += 1
            return {"state": "COMPLETED", "message": "wrong"}

        organizer._organizer_verify_history = verify
        organizer._organizer_execute_task = execute
        result = organizer._organizer_run_claimed({"run_mode": "verify"})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(calls, {"verify": 1, "execute": 0})

    def test_completion_callback_dispatches_next_immediately(self):
        """一个任务收口后必须立即触发下一次 dispatch，而不是等 heartbeat。"""
        organizer = self.new_organizer()
        organizer._organizer_lock = threading.RLock()
        organizer._organizer_owner_id = "owner"
        organizer._organizer_future = Future()
        tasks = {
            "/A.mkv": {
                "path": "/A.mkv",
                "state": "RUNNING",
                "lease_owner": "owner",
                "lease_until": time.time() + 60,
            }
        }
        organizer._organizer_tasks = lambda: tasks
        organizer._organizer_save_tasks = lambda value: tasks.update(value)
        organizer._organizer_history_append = lambda **kwargs: None
        organizer._organizer_status_update = lambda **kwargs: None
        calls = {"dispatch": 0}

        def dispatch():
            calls["dispatch"] += 1
            return {"scheduled": False, "reason": "no_ready"}

        organizer._organizer_dispatch_next = dispatch
        future = Future()
        future.set_result({"state": "COMPLETED", "message": "done"})
        organizer._organizer_done_callback(future)
        self.assertEqual(tasks["/A.mkv"]["state"], "COMPLETED")
        self.assertEqual(calls["dispatch"], 1)

    def test_stopping_instance_does_not_restart_executor(self):
        """热重载旧实例 stopping 后不能继续提交任务。"""
        organizer = self.new_organizer()
        organizer._organizer_stopping = True
        result = organizer._organizer_dispatch_next()
        self.assertEqual(result["reason"], "stopping")


if __name__ == "__main__":
    unittest.main()
