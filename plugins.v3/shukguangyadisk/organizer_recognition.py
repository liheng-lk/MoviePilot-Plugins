"""光鸭自动整理的 MoviePilot 识别上下文桥。

本模块只负责从文件名、父目录和 MoviePilot 目录配置提取高置信度媒体上下文，
最终媒体识别、分类、重命名、整理方式、覆盖、刮削与历史仍由 MoviePilot 负责。
运行时事件注册独立到 :mod:`organizer_runtime`，持久状态由 :mod:`organizer_state`
维护，避免识别规则同时承担事件总线和状态机职责。
"""

from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Any, Optional, Tuple

from app.application.directory import DirectoryHelper
from app.chain.transfer import TransferChain
from app.domain.metainfo import MetaInfo
from app.runtime.events import Event
from app.schemas.types import MediaType
from app.schemas.workflow import FileItem
from app.sdk.logging import logger

from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin
from .organizer_runtime import bind_organizer_runtime


class GuangYaOrganizerMixin(_BaseOrganizerMixin):
    """为光鸭远程监控补齐类型/目录上下文和 MoviePilot 最终结果回执。"""

    _episode_prefix_re = re.compile(
        r"^\s*(?P<episode>\d{1,3})(?P<tail>(?:(?:\s|~|[-_.]|\[|【|\().*)?)$"
    )
    _season_dir_re = re.compile(
        r"^(?:(?:s|season)\s*0*(?P<latin>\d{1,2})|第?\s*0*(?P<cn>\d{1,2})\s*季)$",
        re.IGNORECASE,
    )
    _sxe_re = re.compile(
        r"(?:^|[^A-Za-z0-9])S0*(?P<season>\d{1,2})[\s._-]*E0*(?P<episode>\d{1,3})(?=$|[^0-9])",
        re.IGNORECASE,
    )
    _x_episode_re = re.compile(
        r"(?:^|[^0-9])(?P<season>\d{1,2})x0*(?P<episode>\d{1,3})(?=$|[^0-9])",
        re.IGNORECASE,
    )
    _cn_episode_re = re.compile(r"第\s*0*(?P<episode>\d{1,3})\s*(?:集|话|話)")
    _episode_only_re = re.compile(
        r"(?:^|[\s._\-\[【(])(?:EP?|第)\s*0*(?P<episode>\d{1,3})(?=$|[\s._\-\]】)])",
        re.IGNORECASE,
    )
    _series_folder_re = re.compile(
        r"(?:\bS0*\d{1,2}\b|\bSeason\s*0*\d{1,2}\b|全\s*\d+\s*集|更新至?\s*\d+\s*集|第?\s*\d+\s*季)",
        re.IGNORECASE,
    )
    _bracket_block_re = re.compile(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)")
    _site_prefix_re = re.compile(
        r"^(?:(?:\[[^\]]*(?:www\.|\.com|\.net|发布|發佈|制作|製作)[^\]]*\]|"
        r"【[^】]*(?:www\.|\.com|\.net|发布|發佈|制作|製作)[^】]*】)\s*)+",
        re.IGNORECASE,
    )
    _release_cut_re = re.compile(
        r"(?:\[|【|"
        r"[._\s-]+S0*\d{1,2}(?=$|[._\s-])|"
        r"[._\s-]+Season\s*0*\d{1,2}(?=$|[._\s-])|"
        r"[._\s-]+(?:19|20)\d{2}(?=$|[._\s-])|"
        r"[._\s-]+(?:2160p|1080p|720p|WEB[-_. ]?DL|WEBRip|BluRay|HDTV)(?=$|[._\s-]))",
        re.IGNORECASE,
    )
    _year_re = re.compile(r"(?:19|20)\d{2}")
    _meaningful_title_re = re.compile(r"[A-Za-z\u3400-\u9fff]")
    _cjk_re = re.compile(r"[\u3400-\u9fff]")

    _tv_root_dirs = {
        "tv", "tvshows", "tv shows", "series", "shows", "电视剧", "電視劇", "剧集", "劇集",
        "连续剧", "連續劇", "动漫", "動漫", "动画", "動畫", "番剧", "番劇", "anime",
    }
    _movie_root_dirs = {"movie", "movies", "film", "films", "电影", "電影", "影片"}
    _generic_title_dirs = {
        "tv", "tvshows", "tv shows", "series", "shows", "电视剧", "電視劇", "剧集", "劇集",
        "连续剧", "連續劇", "动漫", "動漫", "动画", "動畫", "番剧", "番劇", "anime",
        "电影", "電影", "movie", "movies", "film", "films", "影片", "media", "download", "downloads",
        "光鸭媒体库", "光鴨媒體庫",
    }

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

    def init_plugin(self, config: dict = None) -> None:
        """初始化完成后绑定当前真实实例，热重载只让最新实例接收事件。"""
        super().init_plugin(config)
        bind_organizer_runtime(self)

    @classmethod
    def _clean_title_hint(cls, value: str) -> str:
        value = cls._site_prefix_re.sub("", str(value or "").strip())
        value = re.sub(r"[._]+", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip(" ._-~[]【】()")

    @classmethod
    def _is_useful_title(cls, value: str) -> bool:
        value = cls._clean_title_hint(value)
        if not value or not cls._meaningful_title_re.search(value):
            return False
        normalized = re.sub(r"[._-]+", " ", value).strip().casefold()
        return normalized not in cls._generic_title_dirs

    @classmethod
    def _release_parent_title(cls, event_path: Path) -> str:
        """从发布组目录提取真正标题，去掉站点前缀、标签、季号、年份和画质尾巴。"""
        raw = cls._site_prefix_re.sub("", str(event_path.parent.name or "").strip())
        if not raw:
            return ""
        head = cls._release_cut_re.split(raw, maxsplit=1)[0]
        cleaned = cls._clean_title_hint(head)
        return cleaned if cls._is_useful_title(cleaned) else ""

    @classmethod
    def _nearest_title_dir(cls, event_path: Path) -> str:
        """从最近父目录向上寻找非泛化、非纯季目录的媒体标题目录。"""
        for parent in list(event_path.parents)[:6]:
            name = str(parent.name or "").strip()
            if not name or cls._season_dir_re.fullmatch(name):
                continue
            cleaned = cls._clean_title_hint(name)
            if cls._is_useful_title(cleaned):
                return cleaned
        return ""

    @classmethod
    def _title_before_match(cls, stem: str, start: int) -> str:
        """明确 S/E 标记出现时优先提取文件名自身标题。"""
        prefix = cls._clean_title_hint(stem[:start])
        return prefix if cls._is_useful_title(prefix) else ""

    @classmethod
    def _preferred_episode_title(cls, event_path: Path, stem: str, match_start: int) -> str:
        """文件名标题可靠时使用文件名；父目录有本地化中文标题时优先使用中文标题。"""
        file_title = cls._title_before_match(stem, match_start)
        parent_title = cls._release_parent_title(event_path)
        if parent_title and cls._cjk_re.search(parent_title) and not cls._cjk_re.search(file_title or ""):
            return parent_title
        return file_title or parent_title or cls._nearest_title_dir(event_path)

    @classmethod
    def _root_media_type(cls, event_path: Path) -> Optional[MediaType]:
        for parent in list(event_path.parents)[:8]:
            normalized = re.sub(r"[._-]+", " ", str(parent.name or "")).strip().casefold()
            if normalized in cls._tv_root_dirs:
                return MediaType.TV
            if normalized in cls._movie_root_dirs:
                return MediaType.MOVIE
        return None

    def _configured_media_type(self, event_path: Path) -> Optional[MediaType]:
        """MoviePilot 用户显式目录配置优先于普通目录名称启发式。"""
        names_getter = getattr(self, "_storage_names", None)
        storage_names = names_getter() if callable(names_getter) else {self._disk_name}
        matches = []
        for directory in DirectoryHelper().get_dirs():
            if str(getattr(directory, "storage", "") or "") not in storage_names:
                continue
            download_path = str(getattr(directory, "download_path", "") or "").strip()
            media_type = str(getattr(directory, "media_type", "") or "").strip()
            if not download_path or not media_type:
                continue
            try:
                if event_path.is_relative_to(Path(download_path)):
                    matches.append(directory)
            except (TypeError, ValueError):
                continue
        if not matches:
            return None
        directory = max(matches, key=lambda item: len(Path(item.download_path).parts))
        try:
            return MediaType(directory.media_type)
        except (TypeError, ValueError):
            logger.warning(
                "【光鸭云盘助手】【自动整理】MoviePilot 目录 %s 配置了未知媒体类型：%s",
                getattr(directory, "download_path", ""),
                getattr(directory, "media_type", ""),
            )
            return None

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
        if not tail and not season_dir:
            return None

        tail_without_blocks = cls._bracket_block_re.sub("", tail)
        tail_residue = re.sub(r"[\s~._\-\d]+", "", tail_without_blocks)
        if tail_residue:
            return None

        title_dir = cls._clean_title_hint(title_dir)
        if not cls._is_useful_title(title_dir):
            return None
        semantic_parent = cls._year_re.sub("", title_dir)
        semantic_parent = re.sub(r"[^A-Za-z\u3400-\u9fff0-9]+", "", semantic_parent)
        if not cls._meaningful_title_re.search(semantic_parent):
            return None
        return title_dir, max(season, 1), episode

    @classmethod
    def _explicit_episode_context(cls, event_path: Path) -> Optional[Tuple[str, int, int, str]]:
        weak = cls._episode_parent_context(event_path)
        if weak:
            title, season, episode = weak
            return title, season, episode, "父目录 + 数字集号"

        stem = event_path.stem
        for regex, label in ((cls._sxe_re, "SxxExx"), (cls._x_episode_re, "NxE")):
            match = regex.search(stem)
            if not match:
                continue
            season = max(int(match.group("season")), 1)
            episode = int(match.group("episode"))
            if episode <= 0:
                return None
            title = cls._preferred_episode_title(event_path, stem, match.start())
            return title, season, episode, label

        cn_match = cls._cn_episode_re.search(stem)
        if cn_match:
            episode = int(cn_match.group("episode"))
            title = cls._preferred_episode_title(event_path, stem, cn_match.start())
            season = 1
            for parent in list(event_path.parents)[:3]:
                season_dir = cls._season_dir_re.fullmatch(parent.name.strip())
                if season_dir:
                    season = int(season_dir.group("latin") or season_dir.group("cn") or 1)
                    break
            return title, max(season, 1), episode, "第N集/话"

        episode_match = cls._episode_only_re.search(stem)
        if episode_match:
            for parent in list(event_path.parents)[:3]:
                season_dir = cls._season_dir_re.fullmatch(parent.name.strip())
                if not season_dir:
                    continue
                season = int(season_dir.group("latin") or season_dir.group("cn") or 1)
                title = cls._preferred_episode_title(event_path, stem, episode_match.start())
                return title, max(season, 1), int(episode_match.group("episode")), "Season目录 + E/EP"
        return None

    @classmethod
    def _copy_technical_meta(cls, meta: Any, event_path: Path) -> Any:
        file_meta = MetaInfo(event_path.name)
        if not getattr(meta, "year", None) and getattr(file_meta, "year", None):
            meta.year = file_meta.year
        for field in cls._technical_meta_fields:
            value = getattr(file_meta, field, None)
            if value is not None:
                setattr(meta, field, value)
        return meta

    def _build_context_meta(self, event_path: Path) -> Optional[Tuple[Any, MediaType, str]]:
        """判定优先级：明确季集 > MP目录配置 > Season/剧集目录 > TV/Movie根目录。"""
        episode_context = self._explicit_episode_context(event_path)
        if episode_context:
            title, season, episode, reason = episode_context
            title = title or self._clean_title_hint(event_path.stem)
            meta = MetaInfo(f"{title} S{season:02d}E{episode:02d}")
            self._copy_technical_meta(meta, event_path)
            meta.type = MediaType.TV
            meta.begin_season = season
            meta.end_season = season
            meta.total_season = 1
            meta.begin_episode = episode
            meta.end_episode = episode
            meta.total_episode = 1
            return meta, MediaType.TV, reason

        configured_type = self._configured_media_type(event_path)
        root_type = self._root_media_type(event_path)
        parent_names = [str(parent.name or "") for parent in list(event_path.parents)[:4]]
        series_folder = next((name for name in parent_names if self._series_folder_re.search(name)), "")
        inferred_type = configured_type or (MediaType.TV if series_folder else root_type)
        if inferred_type not in {MediaType.TV, MediaType.MOVIE}:
            return None

        if inferred_type == MediaType.TV:
            title = self._release_parent_title(event_path) or self._nearest_title_dir(event_path)
            season = 1
            for parent in list(event_path.parents)[:4]:
                season_dir = self._season_dir_re.fullmatch(parent.name.strip())
                if season_dir:
                    season = int(season_dir.group("latin") or season_dir.group("cn") or 1)
                    break
            meta = MetaInfo(f"{title} S{season:02d}" if title else event_path.name)
            self._copy_technical_meta(meta, event_path)
            meta.type = MediaType.TV
            meta.begin_season = max(season, 1)
            reason = "MoviePilot目录配置=电视剧" if configured_type == MediaType.TV else "目录结构=电视剧"
            return meta, MediaType.TV, reason

        meta = MetaInfo(event_path.name)
        self._copy_technical_meta(meta, event_path)
        meta.type = MediaType.MOVIE
        reason = "MoviePilot目录配置=电影" if configured_type == MediaType.MOVIE else "目录结构=电影"
        return meta, MediaType.MOVIE, reason

    @staticmethod
    def _fileitem_from_cloud_item(item: Any, event_path: Path, storage: str) -> FileItem:
        return FileItem(
            storage=storage,
            path=event_path.as_posix(),
            type="file",
            name=event_path.name,
            basename=event_path.stem,
            extension=event_path.suffix[1:],
            size=int(getattr(item, "size", 0) or 0),
            modify_time=float(getattr(item, "modify_time", 0) or 0),
            fileid=str(getattr(item, "fileid", "") or "") or None,
        )

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """有上下文时显式入 TransferChain；返回值表示是否真正接受到 MP 计划/队列。"""
        event_path = Path(str(getattr(item, "path", "") or ""))
        contextual = self._build_context_meta(event_path)
        if not contextual:
            return super()._dispatch_to_moviepilot(item)

        meta, media_type, reason = contextual
        fileitem = self._fileitem_from_cloud_item(item, event_path, self._disk_name)
        logger.info(
            "【光鸭云盘助手】【自动整理】【识别上下文】%s -> type=%s meta=%s；依据=%s；后续目录/命名/整理仍由 MoviePilot 处理",
            event_path,
            media_type.value,
            getattr(meta, "title", event_path.stem),
            reason,
        )
        result = TransferChain().do_transfer(
            fileitem=fileitem,
            meta=meta,
            mtype=media_type,
        )
        if isinstance(result, tuple):
            return bool(result[0])
        return bool(result)

    def _is_own_transfer_fileitem(self, fileitem: Any) -> bool:
        if not fileitem:
            return False
        storage = str(getattr(fileitem, "storage", "") or "")
        matcher = getattr(self, "_matches_storage", None)
        return bool(matcher(storage)) if callable(matcher) else storage == self._disk_name

    @staticmethod
    def _event_payload(event: Event) -> dict:
        payload = getattr(event, "event_data", None)
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _transfer_target_text(transferinfo: Any) -> str:
        if not transferinfo:
            return ""
        for attr in ("target_item", "target_diritem"):
            item = getattr(transferinfo, attr, None)
            if item and getattr(item, "path", None):
                return str(item.path)
        files = list(getattr(transferinfo, "file_list_new", None) or [])
        return str(files[0]) if files else ""

    def _record_terminal_transfer(self, event: Event, success: bool) -> None:
        payload = self._event_payload(event)
        fileitem = payload.get("fileitem")
        if not self._is_own_transfer_fileitem(fileitem):
            return

        raw_path = str(getattr(fileitem, "path", "") or "")
        if not raw_path or not self._is_monitored_path(raw_path):
            return
        path = self._organize_normalize_path(raw_path)
        fingerprint = self._fingerprint(fileitem)
        transferinfo = payload.get("transferinfo")
        now = time.time()
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if success:
            self._state().mark_completed(path=path, fingerprint=fingerprint)
            target = self._transfer_target_text(transferinfo)
            message = f"MoviePilot 整理完成{f' → {target}' if target else ''}"
            result = "completed"
        else:
            reason = str(getattr(transferinfo, "message", "") or "MoviePilot 整理失败")
            retry = self._state().mark_failed(
                path=path,
                fingerprint=fingerprint,
                now=now,
                reason=reason,
            )
            message = (
                f"MoviePilot 整理失败：{reason}；"
                f"{int(retry.get('delay') or 0)} 秒后自动重试"
            )
            result = "failed"

        self._append_monitor_history({
            "time": now_text,
            "path": path,
            "name": str(getattr(fileitem, "name", "") or Path(path).name),
            "size": int(getattr(fileitem, "size", 0) or 0),
            "result": result,
            "message": message,
        })

        status = dict(self.get_data(self._monitor_status_key) or {})
        counter_key = "mp_completed_total" if success else "mp_failed_total"
        status[counter_key] = int(status.get(counter_key) or 0) + 1
        status.update({
            "last_transfer_at": now_text,
            "last_transfer_path": path,
            "last_transfer_result": result,
            "last_transfer_message": message,
        })
        status.update({f"state_{k}": v for k, v in self._state().stats().items()})
        self._save_monitor_status(**status)
        log = logger.info if success else logger.warning
        log("【光鸭云盘助手】【自动整理】【MP最终结果】%s - %s", path, message)

    def organizer_transfer_complete(self, event: Event) -> None:
        self._record_terminal_transfer(event, success=True)

    def organizer_transfer_failed(self, event: Event) -> None:
        self._record_terminal_transfer(event, success=False)


__all__ = ["GuangYaOrganizerMixin"]
