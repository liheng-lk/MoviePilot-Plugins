"""v3.4.4：中文发布目录只作为 MoviePilot 识别提示，不硬编码媒体身份。

标准整季目录仍保持“一个文件夹一个任务”和 MoviePilot 原生目录批量；当发布目录中存在
明确中文标题而文件名只有英文标题时，先用 MoviePilot 自己的 MediaChain 按“中文标题 +
可用年份”做一次目录级识别。只有 MoviePilot 返回的标题、地区标题、译名或别名与发布
目录一致，且可用年份不冲突时，才把这一 MoviePilot 识别结果用于整包；不通过则停止该
目录，宁可等待人工处理，也不回退到容易误命中的英文文件名识别。

插件不维护 TMDB ID 映射、不写死任何影视作品，也不自行决定媒体库分类。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Tuple

from app.chain.media import MediaChain
from app.chain.transfer import TransferChain
from app.domain.metainfo import MetaInfo
from app.schemas.types import MediaType
from app.schemas.workflow import FileItem
from app.sdk.logging import logger

from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_queue_recovery import GuangYaQueueRecoveryMixin


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_NON_TITLE_RE = re.compile(r"[^0-9A-Za-z\u3400-\u9fff]+")


def _normalize_title(value: Any) -> str:
    return _NON_TITLE_RE.sub("", str(value or "")).casefold()


def _cjk_chars(value: Any) -> set[str]:
    return set(_CJK_RE.findall(str(value or "")))


def _folder_hint(plugin: Any, item: _FolderBatchEnvelope) -> Optional[Tuple[str, Optional[int]]]:
    """返回高置信度中文目录标题及年份；没有明确中文标题时不介入 MP 原生识别。"""
    if not item.directory_mode or not item.members:
        return None

    first_path = Path(str(getattr(item.members[0], "path", "") or ""))
    title_getter = getattr(plugin, "_release_parent_title", None)
    if not callable(title_getter):
        return None
    try:
        title = str(title_getter(first_path) or "").strip()
    except Exception:
        return None
    if not title or not _CJK_RE.search(title):
        return None

    # 年份优先取发布目录，再取首个文件名；无年份时仍可按中文标题识别，但必须通过标题校验。
    year = None
    for text in (str(item.name or ""), first_path.name):
        match = _YEAR_RE.search(text)
        if match:
            year = int(match.group(1))
            break
    return title, year


def _recognized_title_candidates(media: Any) -> list[str]:
    """收集 MoviePilot MediaInfo 中所有可用于核对的标题/译名。

    不能只看 ``title``：例如台湾剧可能以英文主标题返回，但 ``tw_title`` 或 ``names``
    中仍包含正确中文片名。反过来，如果这些字段都与父目录中文标题无关，就不能继续整理。
    """
    values: list[str] = []
    for attr in (
        "title",
        "original_title",
        "original_name",
        "en_title",
        "hk_title",
        "tw_title",
        "sg_title",
        "title_year",
    ):
        value = getattr(media, attr, None)
        if value:
            values.append(str(value))

    for attr in ("names", "aliases"):
        aliases = getattr(media, attr, None)
        if isinstance(aliases, (list, tuple, set)):
            values.extend(str(value) for value in aliases if value)
    return values


def _recognition_matches_hint(title: str, year: Optional[int], media: Any) -> bool:
    """保守校验 MP 返回结果，避免中文目录存在时又误用无关英文同名条目。"""
    if not media:
        return False

    hint_norm = _normalize_title(title)
    hint_cjk = _cjk_chars(title)
    title_ok = False
    for candidate in _recognized_title_candidates(media):
        candidate_norm = _normalize_title(candidate)
        if (
            hint_norm
            and candidate_norm
            and (
                hint_norm == candidate_norm
                or hint_norm in candidate_norm
                or candidate_norm in hint_norm
            )
        ):
            title_ok = True
            break
        candidate_cjk = _cjk_chars(candidate)
        if hint_cjk and candidate_cjk:
            overlap = len(hint_cjk & candidate_cjk) / max(len(hint_cjk), 1)
            if overlap >= 0.70:
                title_ok = True
                break
    if not title_ok:
        return False

    if year:
        media_year = getattr(media, "year", None)
        try:
            if media_year and int(str(media_year)[:4]) != int(year):
                return False
        except (TypeError, ValueError):
            pass
    return True


def _recognize_folder_with_moviepilot(plugin: Any, item: _FolderBatchEnvelope):
    hint = _folder_hint(plugin, item)
    if not hint:
        return None, None, None
    title, year = hint

    hint_text = f"{title} {year}" if year else title
    meta = MetaInfo(hint_text)
    meta.type = MediaType.TV
    if year and not getattr(meta, "year", None):
        meta.year = str(year)

    try:
        media = MediaChain().recognize_by_meta(
            meta,
            mtype=MediaType.TV,
            obtain_images=True,
        )
    except Exception as err:  # noqa: BLE001
        logger.warning(
            "【光鸭云盘助手】【安全识别】目录标题交给 MoviePilot 识别失败: %s - %s",
            hint_text,
            err,
        )
        return hint, None, f"MoviePilot 目录标题识别异常：{err}"

    if not _recognition_matches_hint(title, year, media):
        got_title = str(
            getattr(media, "title_year", None)
            or getattr(media, "title", None)
            or "未识别"
        )
        return hint, None, f"目录标题“{hint_text}”与 MoviePilot 返回“{got_title}”不一致"
    return hint, media, None


def install_safe_recognition_v344() -> None:
    """在 v3.4.2 文件夹批量执行边界外再包一层安全识别；热重载幂等。"""
    if getattr(GuangYaQueueRecoveryMixin, "_guangya_safe_recognition_v344", False):
        return

    previous_execute = GuangYaQueueRecoveryMixin._execute_isolated_transfer

    def execute(self, item: Any):
        if not isinstance(item, _FolderBatchEnvelope) or not item.directory_mode:
            return previous_execute(self, item)

        hint, media, error = _recognize_folder_with_moviepilot(self, item)
        if not hint:
            # 没有明确中文发布标题，不干预；继续 MoviePilot 原生目录识别。
            return previous_execute(self, item)
        title, year = hint
        hint_text = f"{title} {year}" if year else title
        if error or not media:
            message = (
                f"安全识别已停止整理：{error or 'MoviePilot 未识别到目录标题'}；"
                "未按英文文件名继续猜测"
            )
            logger.warning("【光鸭云盘助手】【安全识别】%s - %s", item.path, message)
            return False, message

        directory_item = FileItem(
            storage=self._disk_name,
            path=self._organize_normalize_path(item.path),
            type="dir",
            name=item.name,
            basename=item.name,
            extension="",
            size=item.size,
            modify_time=item.modify_time,
            fileid=None,
        )
        logger.info(
            "【光鸭云盘助手】【安全识别】父目录中文标题仅作 MoviePilot 识别提示: %s -> %s；"
            "无硬编码媒体ID，分类/命名仍由 MoviePilot 决定",
            hint_text,
            getattr(media, "title_year", None) or getattr(media, "title", ""),
        )
        result = TransferChain().do_transfer(
            fileitem=directory_item,
            mediainfo=media,
            mtype=MediaType.TV,
            background=False,
            manual=False,
        )
        if isinstance(result, tuple):
            success = bool(result[0])
            message = result[1]
        else:
            success = bool(result)
            message = ""
        if isinstance(message, dict):
            message = str(message.get("message") or message)
        return success, str(message or "")

    GuangYaQueueRecoveryMixin._execute_isolated_transfer = execute
    GuangYaQueueRecoveryMixin._guangya_safe_recognition_v344 = True


__all__ = ["install_safe_recognition_v344"]
