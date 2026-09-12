"""光鸭 V4 与 MoviePilot V3 原生路径识别合同。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.testing.bootstrap import prepare_backend

prepare_backend()

from app.domain.metainfo import MetaInfoPath
from app.plugins.shukguangyadisk import GuangYaOrganizerV4


class MoviePilotNativeContextTest(unittest.TestCase):
    """弱命名资源必须交给 MoviePilot V3 的 MetaInfoPath，而不是插件自造识别结果。"""

    def test_moviepilot_metainfo_path_merges_series_parent_for_weak_episode_name(self):
        """MoviePilot V3 自身能从 文件/Season/剧名 三层路径合并媒体上下文。"""
        meta = MetaInfoPath(
            Path("/source/炼气十万年 (2023)/Season 1/E200.mp4"),
            force_video=True,
        )
        self.assertIsNotNone(meta)
        # 不要求插件猜 TMDB；只要求原生路径解析没有把弱文件名 E200 当成作品标题。
        title_fields = " ".join(
            str(getattr(meta, name, "") or "")
            for name in ("name", "cn_name", "en_name", "org_string")
        )
        self.assertIn("炼气十万年", title_fields)
        self.assertEqual(getattr(meta, "begin_season", None), 1)
        self.assertEqual(getattr(meta, "begin_episode", None), 200)

    def test_organizer_does_not_override_moviepilot_path_meta(self):
        """V4 do_transfer 调用不得主动传 meta，保留 MoviePilot _build_path_meta/MetaInfoPath。"""
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
            self.assertNotIn("meta", kwargs)
            self.assertIs(kwargs["fileitem"], current)
            self.assertEqual(kwargs["fileitem"].path, current.path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
