"""v3.4.6+：把完整资源目录交给 MoviePilot 做目录级识别与整包整理。

资源目录始终先走 MoviePilot 的路径识别，再把同一个 ``FileItem(type='dir')`` 交给
``TransferChain.do_transfer``。MoviePilot 自己递归扫描目录、逐文件解析季集、决定分类、
目标目录、命名、覆盖与刮削；插件不写死标题、TMDB ID 或媒体 ID。

对于 ``剧集名称/01.mp4``、``22~[4K].mkv`` 等文件名本身缺少剧名/季集语义的目录，
先调用 MoviePilot 自带的 ``recommend_episode_format``。v3.4.11 起优先把扫描阶段已经拿到的
整组文件显式传给 MoviePilot 推荐器，避免远端目录二次取样失败。只有 MoviePilot 自己确认
存在集数定位模板时，才把“电视剧”作为结构类型约束重新交给 MoviePilot 识别目录标题。
监控根散放文件仍不能把整个监控根递归提交。
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from app.chain.media import MediaChain
from app.chain.transfer import TransferChain
from app.schemas.transfer import EpisodeFormat
from app.schemas.types import MediaType
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
    if not context:
        return None, "MoviePilot 未从资源目录生成识别上下文"
    if not getattr(context, "media_info", None):
        return context, "MoviePilot 未从资源目录识别到媒体信息"
    return context, None


def _moviepilot_episode_format(
    transfer_chain: TransferChain,
    directory_item: FileItem,
    fileitems: Optional[List[FileItem]] = None,
) -> Tuple[Optional[EpisodeFormat], Optional[str]]:
    """仅使用 MoviePilot 自带推荐器判断是否存在集数结构。"""
    try:
        state, message, data = transfer_chain.recommend_episode_format(
            fileitem=directory_item,
            fileitems=fileitems or None,
        )
    except Exception as err:  # noqa: BLE001
        return None, f"MoviePilot 集数定位推荐异常：{err}"
    if not state or not isinstance(data, dict):
        return None, str(message or "MoviePilot 未推荐集数定位模板")
    episode_format = str(data.get("episode_format") or "").strip()
    if not episode_format:
        return None, str(message or "MoviePilot 未推荐集数定位模板")
    return EpisodeFormat(format=episode_format), None


def _is_tv_media(media: Any) -> bool:
    media_type = getattr(media, "type", None)
    if media_type == MediaType.TV:
        return True
    value = getattr(media_type, "value", media_type)
    return str(value or "").casefold() in {
        str(getattr(MediaType.TV, "value", MediaType.TV)).casefold(),
        "tv",
        "电视剧",
    }


def _moviepilot_tv_context_from_directory_meta(meta: Any) -> Tuple[Any, Optional[str]]:
    """集数结构已由 MP 确认时，用同一份 MP 目录 meta 约束为电视剧重新识别。"""
    if not meta:
        return None, "MoviePilot 目录上下文缺少 meta_info"
    try:
        media = MediaChain().recognize_by_meta(
            metainfo=meta,
            mtype=MediaType.TV,
            obtain_images=True,
        )
    except Exception as err:  # noqa: BLE001
        return None, f"MoviePilot 电视剧约束识别异常：{err}"
    if not media:
        return None, "MoviePilot 未在电视剧类型下识别到该目录"
    if not _is_tv_media(media):
        return None, "MoviePilot 电视剧约束识别结果类型仍不是电视剧"
    return media, None


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
    """最后覆盖文件夹执行边界，确保完整目录始终由 MoviePilot 接管。"""
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

        # 对所有资源目录都让 MoviePilot 自己判断是否需要集数定位模板；优先复用扫描阶段的整组成员。
        epformat, episode_error = _moviepilot_episode_format(
            transfer_chain=transfer_chain,
            directory_item=directory_item,
            fileitems=list(item.members or []),
        )
        if epformat:
            logger.info(
                "【光鸭云盘助手】【MP目录上下文】MoviePilot 检测到剧集集数模板: %s -> %s",
                item.path,
                epformat.format,
            )
            # 路径识别可能因为 01.mp4 这类文件缺少 SxxExx 而先命中电影。
            # 只有 MP 自己给出 episode_format 后，才使用 MP 的同一目录 meta 约束 TV 重识别。
            if not _is_tv_media(media):
                tv_media, tv_error = _moviepilot_tv_context_from_directory_meta(meta)
                if tv_media:
                    logger.info(
                        "【光鸭云盘助手】【MP目录上下文】集数结构已确认，MoviePilot 按电视剧重新识别: %s -> %s",
                        item.path,
                        getattr(tv_media, "title_year", None) or getattr(tv_media, "title", ""),
                    )
                    media = tv_media
                    recognize_error = None
                else:
                    # 已确认是集数结构时绝不能继续沿用电影结果，否则会造成错误入库。
                    logger.warning(
                        "【光鸭云盘助手】【MP目录上下文】已检测到集数结构，但电视剧识别未确认，暂缓整理: %s - %s",
                        item.path,
                        tv_error or "未知原因",
                    )
                    return False, str(tv_error or "MoviePilot 已检测到集数结构，但电视剧识别未确认")
        elif episode_error:
            logger.debug(
                "【光鸭云盘助手】【MP目录上下文】MoviePilot 未检测到额外集数模板，使用原生解析: %s - %s",
                item.path,
                episode_error,
            )

        if media:
            logger.info(
                "【光鸭云盘助手】【MP目录上下文】MoviePilot 目录识别: %s -> %s；分类=%s；"
                "随后由 MoviePilot 扫描整个目录并整理",
                item.path,
                getattr(media, "title_year", None) or getattr(media, "title", ""),
                getattr(media, "category", None) or "由 MoviePilot 整理阶段决定",
            )
        else:
            logger.warning(
                "【光鸭云盘助手】【MP目录上下文】%s；不做插件硬识别，直接交给 MoviePilot 原生目录整理: %s",
                recognize_error or "MoviePilot 目录识别无结果",
                item.path,
            )

        kwargs = {
            "fileitem": directory_item,
            "background": False,
            "manual": False,
        }
        # mediainfo 只接受 MoviePilot 自己的目录识别结果；epformat 也只接受 MoviePilot 推荐或验证结果。
        if media:
            kwargs["mediainfo"] = media
            media_type = getattr(media, "type", None)
            if media_type:
                kwargs["mtype"] = media_type
        elif epformat:
            kwargs["mtype"] = MediaType.TV
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
