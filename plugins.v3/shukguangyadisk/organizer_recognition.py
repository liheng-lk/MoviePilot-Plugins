"""光鸭自动整理的弱文件名识别桥接。

MoviePilot 的整理规则仍然是唯一的分类、命名和目标目录来源。本模块只在文件名
几乎只剩“集号 + 技术标签”时补一个识别提示，例如：

    启运丹田：开局签到至尊丹田 (2025)/22~[4K][HEVC.AAC][2026.08.19].mp4

这类文件如果直接送入 MetaInfoPath，数字 ``22`` 可能被当成电影标题。本模块将
父目录作为剧名、数字前缀作为集号，随后仍调用 MoviePilot 原生 TransferChain；
目录匹配、分类、重命名、整理方式、覆盖、刮削与整理历史均不在插件内实现。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Tuple

from app.chain.transfer import TransferChain
from app.domain.metainfo import MetaInfo
from app.schemas.types import MediaType
from app.schemas.workflow import FileItem
from app.sdk.logging import logger

from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin


class GuangYaOrganizerMixin(_BaseOrganizerMixin):
    """在原自动监控上补充“父目录剧名 + 数字集号”的最小识别提示。"""

    # 仅接受 1~3 位数字开头；后面只能为空，或以常见分隔符/技术标签起始。
    _episode_prefix_re = re.compile(
        r"^\s*(?P<episode>\d{1,3})(?P<tail>(?:(?:\s|~|[-_.]|\[|【|\().*)?)$"
    )
    _season_dir_re = re.compile(
        r"^(?:(?:s|season)\s*0*(?P<latin>\d{1,2})|第?\s*0*(?P<cn>\d{1,2})\s*季)$",
        re.IGNORECASE,
    )
    _bracket_block_re = re.compile(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)")
    _year_re = re.compile(r"(?:19|20)\d{2}")
    _meaningful_title_re = re.compile(r"[A-Za-z\u3400-\u9fff]")
    _generic_title_dirs = {
        "tv",
        "电视剧",
        "剧集",
        "电影",
        "movie",
        "movies",
        "media",
        "download",
        "downloads",
        "光鸭媒体库",
    }
    # 仅从原文件名补回资源技术信息，绝不把文件名里的“22/2026”等标题或年份
    # 覆盖到父目录剧名提示中。
    _technical_meta_fields = (
        "resource_type",
        "resource_effect",
        "resource_pix",
        "resource_team",
        "web_source",
        "video_encode",
        "video_bit",
        "audio_encode",
        "fps",
    )

    @classmethod
    def _episode_parent_context(cls, event_path: Path) -> Optional[Tuple[str, int, int]]:
        """识别“数字集号文件 + 有意义父目录”，返回 (剧名, 季, 集)。"""
        stem = event_path.stem
        match = cls._episode_prefix_re.match(stem)
        if not match:
            return None

        episode = int(match.group("episode"))
        if episode <= 0:
            return None

        tail = match.group("tail") or ""
        parent_name = event_path.parent.name.strip()
        season = 1
        title_dir = parent_name
        season_dir = cls._season_dir_re.fullmatch(parent_name)
        if season_dir:
            season = int(season_dir.group("latin") or season_dir.group("cn") or 1)
            title_dir = event_path.parent.parent.name.strip()

        # 裸数字文件仅在明确 Season/Sxx 目录下启用；普通目录中的 22.mp4 继续交给 MP 原识别。
        if not tail and not season_dir:
            return None

        # 技术标签允许出现在 [] / 【】 / () 内；括号外若还有文字，说明文件名本身有标题，不接管。
        tail_without_blocks = cls._bracket_block_re.sub("", tail)
        tail_residue = re.sub(r"[\s~._\-\d]+", "", tail_without_blocks)
        if tail_residue:
            return None

        if not title_dir or title_dir.casefold() in cls._generic_title_dirs:
            return None
        if not cls._meaningful_title_re.search(title_dir):
            return None

        # 例如父目录就是“22 (2025)”时，不把电影 22 误判成第 22 集。
        semantic_parent = cls._year_re.sub("", title_dir)
        semantic_parent = re.sub(r"[^A-Za-z\u3400-\u9fff0-9]+", "", semantic_parent)
        if not cls._meaningful_title_re.search(semantic_parent):
            return None

        return title_dir, max(season, 1), episode

    @classmethod
    def _build_parent_episode_meta(
        cls, event_path: Path
    ) -> Optional[Tuple[Any, str, int, int]]:
        context = cls._episode_parent_context(event_path)
        if not context:
            return None
        title, season, episode = context

        # 用 MoviePilot 自己的 MetaInfo 解析剧名和 S/E，不另写媒体识别器。
        meta = MetaInfo(f"{title} S{season:02d}E{episode:02d}")
        file_meta = MetaInfo(event_path.name)
        for field in cls._technical_meta_fields:
            value = getattr(file_meta, field, None)
            if value is not None:
                setattr(meta, field, value)

        meta.type = MediaType.TV
        meta.begin_season = season
        meta.end_season = season
        meta.total_season = 1
        meta.begin_episode = episode
        meta.end_episode = episode
        meta.total_episode = 1
        return meta, title, season, episode

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """弱文件名走父目录识别提示，其余文件继续走 MoviePilot TransferDispatcher。"""
        event_path = Path(str(getattr(item, "path", "") or ""))
        hinted = self._build_parent_episode_meta(event_path)
        if not hinted:
            return super()._dispatch_to_moviepilot(item)

        meta, title, season, episode = hinted
        fileitem = FileItem(
            storage=self._disk_name,
            path=event_path.as_posix(),
            type="file",
            name=event_path.name,
            basename=event_path.stem,
            extension=event_path.suffix[1:],
            size=int(getattr(item, "size", 0) or 0),
            modify_time=float(getattr(item, "modify_time", 0) or 0),
            fileid=str(getattr(item, "fileid", "") or "") or None,
        )

        logger.info(
            "【光鸭云盘助手】【自动整理】【识别修正】弱文件名使用父目录剧名：%s -> %s S%02dE%02d；后续目录/命名仍由 MoviePilot 处理",
            event_path,
            title,
            season,
            episode,
        )
        result = TransferChain().do_transfer(
            fileitem=fileitem,
            meta=meta,
            mtype=MediaType.TV,
        )
        if isinstance(result, tuple):
            return bool(result[0])
        return bool(result)


__all__ = ["GuangYaOrganizerMixin"]
