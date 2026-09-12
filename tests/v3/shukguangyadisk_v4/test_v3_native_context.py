"""光鸭 V4 与 MoviePilot V3 原生路径识别合同。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.testing.bootstrap import prepare_backend

prepare_backend()

from app.plugins.shukguangyadisk import GuangYaOrganizerV4


class MoviePilotNativeContextTest(unittest.TestCase):
    """弱命名资源必须把完整路径交给 MoviePilot，而不是插件自造识别结果。"""

    def test_organizer_does_not_override_moviepilot_path_meta(self):
        """V4 do_transfer 不主动传 meta，保留 V3 _build_path_meta/MetaInfoPath 识别链。"""
        organizer = object.__new__(GuangYaOrganizerV4)
        organizer._disk_name = "光鸭云盘助手"
        current = SimpleNamespace(
            path="/source/炼气十万年 (2023)/Season 1/E200.mp4",
            name="E200.mp4",
            type="file",
            fileid="episode-200",
            size=1024,
            modify_time=1,
        )
        organizer._guangya_api = SimpleNamespace(refresh_item=lambda _path: current)
        organizer._organizer_history_gate = lambda _current: {"ok": True, "message": ""}
        organizer._organizer_directory_context = lambda _path: (None, None)
        organizer._organizer_episode_format = lambda *_args, **_kwargs: None
        organizer._organizer_verify_history = lambda _task: {
            "state": "COMPLETED",
            "message": "verified",
        }

        calls = []

        class FakeTransferChain:
            def do_transfer(self, **kwargs):
                calls.append(dict(kwargs))
                if kwargs.get("preview"):
                    return True, {
                        "items": [
                            {
                                "source": current.path,
                                "target": "/library/炼气十万年 (2023)/Season 1/炼气十万年 - S01E200.mp4",
                                "success": True,
                            }
                        ]
                    }
                return True, "ok"

        with patch(
            "app.plugins.shukguangyadisk.TransferChain",
            return_value=FakeTransferChain(),
        ):
            result = organizer._organizer_execute_task(
                {"path": current.path, "attempts": 1}
            )

        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(len(calls), 2)
        for kwargs in calls:
            # MoviePilot V3 在 meta 缺省时，会使用 fileitem.path 构建 MetaInfoPath；
            # 因此必须保留完整的 剧名/Season/文件名 路径，且不得抢先塞自造 meta。
            self.assertNotIn("meta", kwargs)
            self.assertIs(kwargs["fileitem"], current)
            self.assertEqual(
                kwargs["fileitem"].path,
                "/source/炼气十万年 (2023)/Season 1/E200.mp4",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
