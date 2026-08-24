"""光鸭自动整理的 MoviePilot 识别与运行时桥接。

MoviePilot 仍然是唯一的媒体识别、目录规则、重命名、整理方式、覆盖、刮削和历史来源。
本模块只解决自定义远程存储监控与 MoviePilot 原生整理链之间的上下文缺口：

1. 为光鸭自定义存储补齐当前 MoviePilot V3 的 StorageOperSelection 运行时桥，确保
   TransferChain 真正拿到光鸭源存储操作对象，而不是“已提交队列”后在后台整理阶段失败。
2. 在文件名存在明确 SxxExx / 1x02 / 第N集 等证据，或目录结构明确为 TV / Movie 时，
   把“媒体类型 + 父目录标题 + 季集”作为提示交给 MoviePilot，避免剧集被当成电影。
3. 监听 MoviePilot 最终 TransferComplete / TransferFailed，成功才记录最终入库结果；
   失败会重新开放该源文件，让自动监控下一轮能够重试，而不是永远停在“已提交 MP”。
4. v3.2.2 首次启动会一次性重新开放 v3.2.1 已标记 seen 的文件，利用 MoviePilot
   自身整理历史挡住已成功项，并让此前“已提交但后台失败”的文件重新进入整理链。
"""

from __future__ import annotations

import datetime
import re
import time
import weakref
from pathlib import Path
from typing import Any, Optional, Tuple

from app.application.directory import DirectoryHelper
from app.chain.transfer import TransferChain
from app.domain.metainfo import MetaInfo
from app.runtime.events import Event, eventmanager
from app.schemas.types import ChainEventType, EventType, MediaType
from app.schemas.workflow import FileItem
from app.sdk.logging import logger

from .organizer import GuangYaOrganizerMixin as _BaseOrganizerMixin


_ACTIVE_PLUGIN_REF: Optional[weakref.ReferenceType[Any]] = None


def _active_plugin() -> Optional[Any]:
    ref = _ACTIVE_PLUGIN_REF
    return ref() if ref else None


@eventmanager.register(ChainEventType.StorageOperSelection)
def _guangya_storage_selection_bridge(event: Event) -> None:
    """自由函数桥不依赖 mixin 类名绑定，直接把 V3 链式事件交给当前光鸭插件实例。"""
    plugin = _active_plugin()
    if not plugin or not getattr(plugin, "_enabled", False):
        return
    plugin.storage_oper_selection(event)


@eventmanager.register(EventType.TransferComplete)
def _guangya_transfer_complete_bridge(event: Event) -> None:
    plugin = _active_plugin()
    if not plugin or not getattr(plugin, "_enabled", False):
        return
    plugin.organizer_transfer_complete(event)


@eventmanager.register(EventType.TransferFailed)
def _guangya_transfer_failed_bridge(event: Event) -> None:
    plugin = _active_plugin()
    if not plugin or not getattr(plugin, "_enabled", False):
        return
    plugin.organizer_transfer_failed(event)


class GuangYaOrganizerMixin(_BaseOrganizerMixin):
    """为光鸭远程监控补齐类型/目录上下文、存储桥和最终结果回执。"""

    _v322_migration_key = "organize_monitor_v322_reopen_seen"

    # 仅接受 1~3 位数字开头；后面只能为空，或以常见分隔符/技术标签起始。
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
    _year_re = re.compile(r"(?:19|20)\d{2}")
    _meaningful_title_re = re.compile(r"[A-Za-z\u3400-\u9fff]")

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

    # 仅从原文件名补回资源技术信息，不覆盖父目录/路径推断出的标题、季、集和类型。
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
        """记录当前真实插件实例，供自由函数事件桥在热重载后始终指向新实例。"""
        global _ACTIVE_PLUGIN_REF
        _ACTIVE_PLUGIN_REF = weakref.ref(self)
        super().init_plugin(config)

    def init_organizer_monitor(self, force: bool = False) -> None:
        super().init_organizer_monitor(force=force)
        self._migrate_v322_monitor_state_once()

    def _migrate_v322_monitor_state_once(self) -> None:
        """重新开放 v3.2.1 仅“提交成功”就标记 seen 的文件，修复升级后永久不重试。"""
        marker = self.get_data(self._v322_migration_key) or {}
        if isinstance(marker, dict) and marker.get("done"):
            return
        state = dict(self.get_data(self._monitor_state_key) or {})
        seen = dict(state.get("seen") or {})
        reopened = len(seen)
        state["seen"] = {}
        state["pending"] = {}
        state["migration"] = "v3.2.2-reopen-submitted"
        state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_data(self._monitor_state_key, state)
        self.save_data(
            self._v322_migration_key,
            {"done": True, "time": time.time(), "reopened": reopened},
        )
        if reopened:
            logger.warning(
                "【光鸭云盘助手】【自动整理】v3.2.2 重新开放 %s 个旧 seen 文件；已成功项由 MoviePilot 整理历史门控，旧版仅提交但后台失败的文件将重新尝试",
                reopened,
            )

    @classmethod
    def _clean_title_hint(cls, value: str) -> str:
        value = cls._site_prefix_re.sub("", str(value or "").strip())
        return value.strip(" ._-~[]【】()")

    @classmethod
    def _nearest_title_dir(cls, event_path: Path) -> str:
        """从最近父目录向上寻找非泛化、非纯季目录的媒体标题目录。"""
        for parent in list(event_path.parents)[:6]:
            name = str(parent.name or "").strip()
            if not name:
                continue
            if cls._season_dir_re.fullmatch(name):
                continue
            normalized = re.sub(r"[._-]+", " ", name).strip().casefold()
            if normalized in cls._generic_title_dirs:
                continue
            cleaned = cls._clean_title_hint(name)
            if cleaned and cls._meaningful_title_re.search(cleaned):
                return cleaned
        return ""

    @classmethod
    def _root_media_type(cls, event_path: Path) -> Optional[MediaType]:
        """读取目录树中的明确 TV/Movie 根目录语义。"""
        for parent in list(event_path.parents)[:8]:
            normalized = re.sub(r"[._-]+", " ", str(parent.name or "")).strip().casefold()
            if normalized in cls._tv_root_dirs:
                return MediaType.TV
            if normalized in cls._movie_root_dirs:
                return MediaType.MOVIE
        return None

    def _configured_media_type(self, event_path: Path) -> Optional[MediaType]:
        """优先复用 MoviePilot 目录配置中的媒体类型，不要求该目录由宿主 watcher 负责监控。"""
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

        # 裸数字文件仅在明确 Season/Sxx 目录下启用；普通目录中的 22.mp4 继续交给 MP 原识别。
        if not tail and not season_dir:
            return None

        # 技术标签允许出现在 [] / 【】 / () 内；括号外若还有文字，说明文件名本身有标题，不接管。
        tail_without_blocks = cls._bracket_block_re.sub("", tail)
        tail_residue = re.sub(r"[\s~._\-\d]+", "", tail_without_blocks)
        if tail_residue:
            return None

        title_dir = cls._clean_title_hint(title_dir)
        if not title_dir or re.sub(r"[._-]+", " ", title_dir).strip().casefold() in cls._generic_title_dirs:
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
    def _explicit_episode_context(cls, event_path: Path) -> Optional[Tuple[str, int, int, str]]:
        """从完整文件名/目录中识别明确的电视剧季集证据。"""
        weak = cls._episode_parent_context(event_path)
        if weak:
            title, season, episode = weak
            return title, season, episode, "父目录 + 数字集号"

        stem = event_path.stem
        for regex, label in ((cls._sxe_re, "SxxExx"), (cls._x_episode_re, "NxE")):
            match = regex.search(stem)
            if match:
                season = max(int(match.group("season")), 1)
                episode = int(match.group("episode"))
                if episode <= 0:
                    return None
                title = cls._nearest_title_dir(event_path)
                if not title:
                    title = cls._clean_title_hint(stem[: match.start()])
                return title, season, episode, label

        cn_match = cls._cn_episode_re.search(stem)
        if cn_match:
            episode = int(cn_match.group("episode"))
            title = cls._nearest_title_dir(event_path) or cls._clean_title_hint(stem[: cn_match.start()])
            season = 1
            for parent in list(event_path.parents)[:3]:
                season_dir = cls._season_dir_re.fullmatch(parent.name.strip())
                if season_dir:
                    season = int(season_dir.group("latin") or season_dir.group("cn") or 1)
                    break
            return title, max(season, 1), episode, "第N集/话"

        # E43 / EP43 只有在 Season/Sxx 目录下才采用，避免把编码/版本数字误当集号。
        episode_match = cls._episode_only_re.search(stem)
        if episode_match:
            for parent in list(event_path.parents)[:3]:
                season_dir = cls._season_dir_re.fullmatch(parent.name.strip())
                if not season_dir:
                    continue
                season = int(season_dir.group("latin") or season_dir.group("cn") or 1)
                title = cls._nearest_title_dir(event_path)
                return title, max(season, 1), int(episode_match.group("episode")), "Season目录 + E/EP"
        return None

    @classmethod
    def _copy_technical_meta(cls, meta: Any, event_path: Path) -> Any:
        file_meta = MetaInfo(event_path.name)
        for field in cls._technical_meta_fields:
            value = getattr(file_meta, field, None)
            if value is not None:
                setattr(meta, field, value)
        return meta

    def _build_context_meta(self, event_path: Path) -> Optional[Tuple[Any, MediaType, str]]:
        """综合文件名、父目录、MP目录设置形成高置信度类型提示；无法确定则不接管。"""
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

        # 文件本身没有明确集号时，再看目录结构。剧集目录中的普通视频仍明确给 TV 类型，
        # 但不虚构集号；具体标题/季集继续由 MoviePilot MetaInfo 解析。
        root_type = self._root_media_type(event_path)
        configured_type = self._configured_media_type(event_path)
        parent_names = [str(parent.name or "") for parent in list(event_path.parents)[:4]]
        series_folder = next((name for name in parent_names if self._series_folder_re.search(name)), "")
        inferred_type = MediaType.TV if series_folder else (root_type or configured_type)
        if inferred_type not in {MediaType.TV, MediaType.MOVIE}:
            return None

        if inferred_type == MediaType.TV:
            title = self._nearest_title_dir(event_path)
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
            return meta, MediaType.TV, "目录结构/MP目录配置=电视剧"

        meta = MetaInfo(event_path.name)
        self._copy_technical_meta(meta, event_path)
        meta.type = MediaType.MOVIE
        return meta, MediaType.MOVIE, "目录结构/MP目录配置=电影"

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
        """有高置信度上下文时显式传给 MoviePilot；其余继续走宿主 TransferDispatcher。"""
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
        if not raw_path:
            return
        path = self._organize_normalize_path(raw_path)
        transferinfo = payload.get("transferinfo")
        now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state = dict(self.get_data(self._monitor_state_key) or {})
        seen = dict(state.get("seen") or {})
        pending = dict(state.get("pending") or {})

        if success:
            seen[path] = self._fingerprint(fileitem)
            pending.pop(path, None)
            target = self._transfer_target_text(transferinfo)
            message = f"MoviePilot 整理完成{f' → {target}' if target else ''}"
            result = "completed"
        else:
            # 关键：MP 后台失败时撤销“seen”，让下一轮扫描重新进入稳定等待和 MP 重试门控。
            seen.pop(path, None)
            pending.pop(path, None)
            reason = str(getattr(transferinfo, "message", "") or "MoviePilot 整理失败")
            message = f"MoviePilot 整理失败：{reason}；已重新开放自动重试"
            result = "failed"

        state["seen"] = seen
        state["pending"] = pending
        state["updated_at"] = now_text
        self.save_data(self._monitor_state_key, state)
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
        self.save_data(self._monitor_status_key, status)
        log = logger.info if success else logger.warning
        log("【光鸭云盘助手】【自动整理】【MP最终结果】%s - %s", path, message)

    def organizer_transfer_complete(self, event: Event) -> None:
        self._record_terminal_transfer(event, success=True)

    def organizer_transfer_failed(self, event: Event) -> None:
        self._record_terminal_transfer(event, success=False)


__all__ = ["GuangYaOrganizerMixin"]
