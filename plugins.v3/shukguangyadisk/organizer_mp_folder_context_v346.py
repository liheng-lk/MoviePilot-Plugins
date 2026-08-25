"""v3.4.6：把完整资源目录交给 MoviePilot 做目录级识别与整包整理。

旧的 v3.4.4 安全识别会先从中文父目录提取标题，再单独调用 MediaChain 识别；虽然识别器
仍来自 MoviePilot，但这会把插件放在“先猜标题”的位置。v3.4.6 改成直接使用 MoviePilot
公开的 ``MediaChain.recognize_by_path`` 对真实资源目录路径做识别，然后把同一个目录
``FileItem(type='dir')`` 交给 ``TransferChain.do_transfer``。MoviePilot 自己递归扫描目录、
逐文件解析季集、决定分类/目标目录/命名/覆盖/刮削。

对于 22~[4K] 等弱集号目录，不再由插件自己拼剧集 MetaInfo；只调用 MoviePilot 自带的
``TransferChain.recommend_episode_format`` 推荐集数定位模板，再由同一个目录批次执行。
监控根目录散放文件仍不能把整个监控根递归提交给 MoviePilot，因此保留既有单文件兼容路径。
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from app.chain.media import MediaChain
from app.chain.transfer import TransferChain
from app.schemas.transfer import EpisodeFormat
from app.schemas.workflow import FileItem
from app.sdk.logging import logger

from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


def _is_monitor_root_folder_task(plugin: Any, item: _FolderBatchEnvelope) -> bool:
    return plugin._organize_normalize_path(item.path) == plugin._organize_normalize_path(
        plugin._organize_monitor_path
    )


def _directory_fileitem(plugin: Any, item: _FolderBatchEnvelope) -> FileItem:
    """仅描述真实源目录；目录内容由 MoviePilot StorageChain 自己重新读取。"""
    return FileItem(
        storage=plugin._disk_name,
        path=plugin._organize_normalize_path(item.path),
        type="dir",
        name=item.name,
        basename=item.name,
        extension="",
        size=item.size,
        modify_time=item.modify_time,
        fileid=None,
    )


def _moviepilot_directory_context(path: str) -> Tuple[Any, Optional[str]]:
    """完全使用 MoviePilot 的路径识别入口，不提取标题、不写死媒体 ID。"""
    try:
        context = MediaChain().recognize_by_path(path, obtain_images=True)
    except Exception as err:  # noqa: BLE001 - MoviePilot compatibility boundary
        return None, f"MoviePilot 目录路径识别异常：{err}"
    if not context or not getattr(context, "media_info", None):
        return None, "MoviePilot 未从资源目录识别到媒体信息"
    return context, None


def _moviepilot_episode_format(
    transfer_chain: TransferChain,
    directory_item: FileItem,
) -> Tuple[Optional[EpisodeFormat], Optional[str]]:
    """弱集号目录仅使用 MoviePilot 自带推荐器，不在插件里维护正则规则。"""
    try:
        state, message, data = transfer_chain.recommend_episode_format(
            fileitem=directory_item,
            fileitems=None,
        )
    except Exception as err:  # noqa: BLE001
        return None, f"MoviePilot 集数定位推荐异常：{err}"
    if not state or not isinstance(data, dict):
        return None, str(message or "MoviePilot 未推荐集数定位模板")
    episode_format = str(data.get("episode_format") or "").strip()
    if not episode_format:
        return None, str(message or "MoviePilot 未推荐集数定位模板")
    return EpisodeFormat(format=episode_format), None


def _normalize_result(result: Any) -> Tuple[bool, str]:
    if isinstance(result, tuple):
        success = bool(result[0])
        message = result[1]
    else:
        success = bool(result)
        message = ""
    if isinstance(message, dict):
        message = str(message.get("message") or message)
    return success, str(message or "")


def install_mp_folder_context_v346() -> None:
    """最后覆盖文件夹执行边界，热更新时也可绕过旧 v3.4.4 安全识别 wrapper。"""
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_mp_folder_context_v346", False):
        return

    previous_execute = GuangYaQueueRecoveryMixin._execute_isolated_transfer

    def execute(self, item: Any):
        if not isinstance(item, _FolderBatchEnvelope):
            return previous_execute(self, item)

        # 监控根散放文件不能把整个根目录递归交给 MP，否则会把所有资源子目录一锅端。
        if _is_monitor_root_folder_task(self, item):
            return previous_execute(self, item)

        directory_item = _directory_fileitem(self, item)
        transfer_chain = TransferChain()

        context, recognize_error = _moviepilot_directory_context(directory_item.path)
        media = getattr(context, "media_info", None) if context else None
        meta = getattr(context, "meta_info", None) if context else None

        if media:
            logger.info(
                "【光鸭云盘助手】【MP目录上下文】MoviePilot 目录识别: %s -> %s；分类=%s；"
                "随后由 MoviePilot 扫描整个目录并整理",
                item.path,
                getattr(media, "title_year", None) or getattr(media, "title", ""),
                getattr(media, "category", None) or "由 MoviePilot 整理阶段决定",
            )
        else:
            # 不再由插件回退到中文标题提取或英文文件名猜测；没有目录识别结果时仍把真实目录
            # 交给 MoviePilot 原生整理链，让宿主按自己的文件级识别规则决定最终结果。
            logger.warning(
                "【光鸭云盘助手】【MP目录上下文】%s；不做插件硬识别，直接交给 MoviePilot 原生目录整理: %s",
                recognize_error or "MoviePilot 目录识别无结果",
                item.path,
            )

        epformat = None
        if not item.directory_mode:
            epformat, episode_error = _moviepilot_episode_format(
                transfer_chain=transfer_chain,
                directory_item=directory_item,
            )
            if epformat:
                logger.info(
                    "【光鸭云盘助手】【MP目录上下文】弱集号目录使用 MoviePilot 推荐集数模板: %s -> %s",
                    item.path,
                    epformat.format,
                )
            elif episode_error:
                logger.info(
                    "【光鸭云盘助手】【MP目录上下文】MoviePilot 未给出集数模板，继续使用原生解析: %s - %s",
                    item.path,
                    episode_error,
                )

        kwargs = {
            "fileitem": directory_item,
            "background": False,
            "manual": False,
        }
        # 只传 MoviePilot 自己从完整目录路径识别出的媒体信息；不传目录 meta，避免整季文件
        # 共享同一集号。逐文件季集仍由 TransferChain 对目录扫描结果自行解析。
        if media:
            kwargs["mediainfo"] = media
            media_type = getattr(media, "type", None)
            if media_type:
                kwargs["mtype"] = media_type
        if epformat:
            kwargs["epformat"] = epformat

        logger.info(
            "【光鸭云盘助手】【MP目录上下文】提交完整资源目录: %s，扫描成员=%s；"
            "识别/分类/命名/目标路径全部由 MoviePilot 执行",
            item.path,
            len(item.members),
        )
        return _normalize_result(transfer_chain.do_transfer(**kwargs))

    GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute
    GuangYaQueueRecoveryMixin._guangya_mp_folder_context_v346 = True


__all__ = ["install_mp_folder_context_v346"]
