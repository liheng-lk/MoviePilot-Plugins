"""v3.4.14：把 MoviePilot 的重命名开关和预览结果变成可观测诊断。

本模块不修改 MoviePilot 的目录配置，也不强制重命名。若 MP 当前目录配置关闭了“智能重命名”，
原名迁移是 MP 的明确规则；若开关已开启，则远端最终文件名必须由存储层 v3.4.14 终态确认。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.application.directory import DirectoryHelper
from app.sdk.logging import logger

from . import organizer_loss_guard_v349 as _loss_guard


def install_rename_diagnostics_v3414() -> None:
    if getattr(_loss_guard, "_guangya_rename_diagnostics_v3414", False):
        return

    previous_build = _loss_guard._build_moviepilot_kwargs
    previous_audit = _loss_guard._audit_preview

    def build(plugin: Any, item: Any):
        transfer_chain, directory_item, kwargs, error = previous_build(plugin, item)
        if error or not kwargs:
            return transfer_chain, directory_item, kwargs, error

        media = kwargs.get("mediainfo")
        directory = None
        if media:
            try:
                directory = DirectoryHelper().get_dir(
                    media=media,
                    storage=plugin._disk_name,
                    src_path=Path(str(getattr(item, "path", "") or "")),
                )
            except Exception as err:  # noqa: BLE001 - MoviePilot config boundary
                logger.debug(
                    "【光鸭云盘助手】【重命名诊断】读取 MoviePilot 目录配置失败: %s - %s",
                    getattr(item, "path", ""),
                    err,
                )

        if directory:
            renaming = bool(getattr(directory, "renaming", False))
            setattr(item, "_guangya_mp_renaming_v3414", renaming)
            setattr(item, "_guangya_mp_directory_name_v3414", str(getattr(directory, "name", "") or ""))
            if renaming:
                logger.info(
                    "【光鸭云盘助手】【重命名诊断】MoviePilot 目录=%s；智能重命名=开启；最终文件名必须与 MP 预览一致",
                    getattr(directory, "name", "") or getattr(directory, "library_path", "") or "未命名目录",
                )
            else:
                logger.warning(
                    "【光鸭云盘助手】【重命名诊断】MoviePilot 目录=%s；智能重命名=关闭；"
                    "按 MP 当前规则本次会保留源文件名。如需统一命名，请在 MoviePilot 对应目录开启智能重命名。",
                    getattr(directory, "name", "") or getattr(directory, "library_path", "") or "未命名目录",
                )
        else:
            setattr(item, "_guangya_mp_renaming_v3414", None)
        return transfer_chain, directory_item, kwargs, None

    def audit(plugin: Any, item: Any, result: Any):
        safe, message, details = previous_audit(plugin, item, result)
        details = dict(details or {})
        renaming = getattr(item, "_guangya_mp_renaming_v3414", None)
        details["moviepilot_renaming"] = renaming

        # 只观察 MoviePilot 自己给出的 source -> target，不计算任何插件命名规则。
        ok, payload, _ = _loss_guard._preview_result(result)
        unchanged = []
        if ok and payload:
            for row in payload.get("items") or []:
                if not isinstance(row, dict) or not row.get("success"):
                    continue
                source = str(row.get("source") or "")
                target = str(row.get("target") or "")
                if source and target and Path(source).name == Path(target).name:
                    unchanged.append(source)
        details["preview_unchanged_names"] = unchanged[:20]
        details["preview_unchanged_count"] = len(unchanged)

        if renaming is True and unchanged:
            logger.info(
                "【光鸭云盘助手】【重命名诊断】MP 预览中有 %s 个文件目标名与源名相同；"
                "这表示 MoviePilot 本次规划本身未改变这些文件名，不由插件二次改名。",
                len(unchanged),
            )
        return safe, message, details

    _loss_guard._build_moviepilot_kwargs = build
    _loss_guard._audit_preview = audit
    _loss_guard._guangya_rename_diagnostics_v3414 = True


__all__ = ["install_rename_diagnostics_v3414"]
