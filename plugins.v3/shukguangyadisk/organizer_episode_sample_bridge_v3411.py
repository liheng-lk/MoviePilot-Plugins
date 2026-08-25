"""v3.4.11：让 v3.4.9 安全预览构建阶段优先使用扫描得到的整组文件样本。

``organizer_loss_guard_v349`` 在历史实现中只把目录交给
``recommend_episode_format(fileitems=None)``，远端存储二次取样可能拿不到足够样本。
本桥接层不改变安全预览逻辑，只在构建目录任务期间把当前 folder envelope 的成员通过
ContextVar 传给 MoviePilot 推荐器，避免 01 4K.mp4 等命名先产生无意义的“未识别集数”。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional, Tuple

from app.chain.transfer import TransferChain
from app.schemas.transfer import EpisodeFormat
from app.schemas.workflow import FileItem

from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_mp_folder_context_v346 import _moviepilot_episode_format as _mp_episode_format
from . import organizer_loss_guard_v349 as _loss_guard


_CURRENT_MEMBERS: ContextVar[Optional[list]] = ContextVar(
    "guangya_episode_member_samples_v3411",
    default=None,
)


def install_episode_sample_bridge_v3411() -> None:
    if getattr(_loss_guard, "_guangya_episode_sample_bridge_v3411", False):
        return

    previous_build = _loss_guard._build_moviepilot_kwargs
    previous_episode_format = _loss_guard._moviepilot_episode_format

    def member_aware_episode_format(
        transfer_chain: TransferChain,
        directory_item: FileItem,
    ) -> Tuple[Optional[EpisodeFormat], Optional[str]]:
        members = _CURRENT_MEMBERS.get()
        if members:
            return _mp_episode_format(
                transfer_chain=transfer_chain,
                directory_item=directory_item,
                fileitems=list(members),
            )
        return previous_episode_format(
            transfer_chain=transfer_chain,
            directory_item=directory_item,
        )

    def build(plugin: Any, item: Any):
        if not isinstance(item, _FolderBatchEnvelope):
            return previous_build(plugin, item)
        token = _CURRENT_MEMBERS.set(list(getattr(item, "members", None) or []))
        try:
            return previous_build(plugin, item)
        finally:
            _CURRENT_MEMBERS.reset(token)

    _loss_guard._moviepilot_episode_format = member_aware_episode_format
    _loss_guard._build_moviepilot_kwargs = build
    _loss_guard._guangya_episode_sample_bridge_v3411 = True


__all__ = ["install_episode_sample_bridge_v3411"]
