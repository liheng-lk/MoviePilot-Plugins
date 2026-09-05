"""v3.6.21：保留被 MoviePilot 同步工作流泛化掉的准入冲突事实。

MoviePilot 当前同步 ``do_transfer(background=False)`` 会在内部记录完整
``TransferAdmissionConflictError`` 堆栈，但公开返回统一压成
``整理任务处理失败，请稍后重试``。v3.6.11 只根据公开 message 判断冲突，因此这种路径会
退化成普通 retry，随后再次以新 planning 撞同一 durable admission。

本层只做观察与光鸭本地状态收口：
- 在宿主 ``TransactionalTransferAdmissionRepository.admit`` 异常边界记录精确冲突；
- 异常原样重新抛出，不改变宿主 admission / planning / lease / settlement；
- 记录存在线程本地，并在每个光鸭私有 Worker 执行前清空，绝不跨任务串线；
- 宿主随后即使只返回通用失败，光鸭 fallback 仍按精确 ``storage + src_path`` 找回冲突；
- 命中的成员写入 v3.6.11 persistent blocked 后，再调用原 fallback，让同批其它普通失败成员
  继续按原语义 retry；已 blocked 成员因为不再 inflight，不会被二次写 retry；
- 其它存储、其它路径、普通执行异常均零行为变化。

不修改 MoviePilot 媒体识别、分类、命名、目标目录、文件操作或 durable 数据。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Tuple

from app.sdk.logging import logger


_REPO_PATCH_FLAG = "_shuk_v3621_admission_probe_wrapped"
_REPO_LOCAL_ATTR = "_shuk_v3621_admission_probe_local"
_EXEC_PATCH_FLAG = "_v3621_admission_probe_wrapped"
_MAX_THREAD_RECORDS = 32


def _admission_repo_class() -> Any:
    from app.db.adapters.transfer.admission import TransactionalTransferAdmissionRepository

    return TransactionalTransferAdmissionRepository


def _execution_class() -> Any:
    # 延迟导入，避免插件入口装配 MRO 时形成反向循环；测试也可以只验证纯观察逻辑。
    from .organizer_execution_v360 import GuangYaOrganizerExecutionV360Mixin

    return GuangYaOrganizerExecutionV360Mixin


def _thread_local() -> threading.local:
    repo_cls = _admission_repo_class()
    local = getattr(repo_cls, _REPO_LOCAL_ATTR, None)
    if not isinstance(local, threading.local):
        local = threading.local()
        setattr(repo_cls, _REPO_LOCAL_ATTR, local)
    return local


def _records() -> List[Dict[str, Any]]:
    try:
        return list(getattr(_thread_local(), "records", []) or [])
    except Exception:
        return []


def clear_admission_probe_v3621() -> None:
    """每个私有 Worker 顶层执行前清空当前线程的旧探针证据。"""
    try:
        _thread_local().records = []
    except Exception:
        return


def _remember_conflict(*, storage: Any, src_path: Any, error: BaseException) -> None:
    try:
        local = _thread_local()
        rows = list(getattr(local, "records", []) or [])
        rows.append(
            {
                "storage": str(storage or ""),
                "src_path": str(src_path or ""),
                "error_type": type(error).__name__,
                "message": str(error or ""),
                "at": time.time(),
            }
        )
        local.records = rows[-_MAX_THREAD_RECORDS:]
    except Exception:
        return


def _is_exact_admission_conflict(error: BaseException) -> bool:
    name = type(error).__name__
    text = str(error or "")
    return name == "TransferAdmissionConflictError" or "整理源文件已按不同输入准入" in text


def install_moviepilot_admission_probe_v3621() -> bool:
    """只观察宿主 admission 异常；永远原样 re-raise，不改变 MoviePilot 行为。"""
    try:
        repo_cls = _admission_repo_class()
    except Exception as err:  # pragma: no cover - 旧宿主兼容兜底
        logger.warning("【光鸭云盘助手】【v3.6.21】【准入探针】宿主 admission repository 不可用: %s", err)
        return False

    _thread_local()
    if bool(getattr(repo_cls, _REPO_PATCH_FLAG, False)):
        return True

    original_admit = repo_cls.admit

    def admit(repository: Any, *args: Any, **kwargs: Any):
        try:
            return original_admit(repository, *args, **kwargs)
        except Exception as err:  # noqa: BLE001 - 仅记录后原样抛出
            if _is_exact_admission_conflict(err):
                _remember_conflict(
                    storage=kwargs.get("storage"),
                    src_path=kwargs.get("src_path"),
                    error=err,
                )
            raise

    setattr(repo_cls, "_shuk_v3621_original_admit", original_admit)
    repo_cls.admit = admit
    setattr(repo_cls, _REPO_PATCH_FLAG, True)
    return True


def _norm(plugin: Any, value: Any) -> str:
    text = str(value or "")
    normalizer = getattr(plugin, "_organize_normalize_path", None)
    if callable(normalizer):
        try:
            return str(normalizer(text) or "")
        except Exception:
            pass
    return text.replace("\\", "/").rstrip("/") or "/"


def _storage_names(plugin: Any) -> set[str]:
    names = {
        str(getattr(plugin, "_disk_name", "光鸭云盘助手") or "光鸭云盘助手"),
        str(getattr(plugin, "_legacy_disk_name", "Shuk-光鸭云盘") or "Shuk-光鸭云盘"),
    }
    for getter_name in ("_storage_names", "_queue_guard_storage_names"):
        getter = getattr(plugin, getter_name, None)
        if not callable(getter):
            continue
        try:
            names.update(str(value) for value in getter() or [] if value)
        except Exception:
            continue
    return {name for name in names if name}


def _member_map(plugin: Any, item: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        members = list(plugin._v360_members(item) or [])
    except Exception:
        members = [item]
    for member in members:
        try:
            path = _norm(plugin, getattr(member, "path", ""))
        except Exception:
            continue
        if path:
            result[path] = member
    return result


def _take_matching_conflicts(plugin: Any, item: Any) -> List[Tuple[Dict[str, Any], Any]]:
    """只消费当前 item 的光鸭冲突，线程内其它记录保留到其对应 fallback。"""
    rows = _records()
    if not rows:
        return []
    members = _member_map(plugin, item)
    allowed_storages = _storage_names(plugin)
    matched: List[Tuple[Dict[str, Any], Any]] = []
    remaining: List[Dict[str, Any]] = []
    for row in rows:
        storage = str(row.get("storage") or "")
        path = _norm(plugin, row.get("src_path"))
        member = members.get(path)
        if storage in allowed_storages and member is not None:
            matched.append((row, member))
        else:
            remaining.append(row)
    try:
        _thread_local().records = remaining[-_MAX_THREAD_RECORDS:]
    except Exception:
        pass
    return matched


def _persist_probe_conflict(plugin: Any, row: Dict[str, Any], member: Any) -> str:
    """复用 v3.6.11 的 persistent admission schema；completed 证据优先终态成功。"""
    path, fingerprint = plugin._v360_member_identity(member)
    decision = dict(plugin._v360_history_decision(member, path) or {})
    if str(decision.get("decision") or "") == "completed":
        plugin._state().mark_completed(path=path, fingerprint=fingerprint)
        return "completed"

    from .organizer_durable_retry_v3611 import _persist_admission_block

    message = str(row.get("message") or "TransferAdmissionConflictError")
    _persist_admission_block(
        plugin,
        path=path,
        fingerprint=fingerprint,
        reason=f"MoviePilot 持久准入冲突：{message}",
        decision=decision,
    )
    return "blocked"


def install_admission_conflict_probe_v3621() -> None:
    """安装精确异常探针，并包住最终 execution fallback。"""
    install_moviepilot_admission_probe_v3621()
    execution_cls = _execution_class()
    if bool(getattr(execution_cls, _EXEC_PATCH_FLAG, False)):
        return

    previous_execute = execution_cls._execute_isolated_transfer
    previous_fallback = execution_cls._fallback_terminal_state
    previous_status = execution_cls.api_organize_monitor_status

    def execute(plugin: Any, item: Any):
        clear_admission_probe_v3621()
        return previous_execute(plugin, item)

    def fallback(plugin: Any, item: Any, success: bool, message: str) -> None:
        blocked = completed = 0
        if not success:
            for row, member in _take_matching_conflicts(plugin, item):
                try:
                    result = _persist_probe_conflict(plugin, row, member)
                except Exception as err:  # noqa: BLE001 - 诊断失败时退回原普通失败语义
                    logger.warning(
                        "【光鸭云盘助手】【v3.6.21】【准入探针】精确冲突收口失败，退回原 fallback: %s",
                        err,
                    )
                    continue
                if result == "completed":
                    completed += 1
                else:
                    blocked += 1

        if blocked or completed:
            plugin._save_monitor_status(
                admission_probe_blocked=blocked,
                admission_probe_completed=completed,
                admission_probe_at=time.time(),
                admission_probe_message="MoviePilot 内部准入异常已在被泛化前精确截获",
            )
            logger.warning(
                "【光鸭云盘助手】【v3.6.21】【准入冲突精确收口】宿主公开返回虽为通用失败，"
                "但 admission 边界已确认冲突：blocked=%s completed=%s；冲突成员不写普通 retry",
                blocked,
                completed,
            )

        # 必须继续走原 fallback：已经 blocked/completed 的成员已退出 inflight，原 v3.6.0
        # 只会把同批仍在 inflight 的其它真实普通失败成员写 retry。
        return previous_fallback(plugin, item, success=success, message=message)

    def api_status(plugin: Any) -> Dict[str, Any]:
        response = previous_status(plugin)
        if isinstance(response, dict) and response.get("success"):
            data = response.setdefault("data", {})
            status = data.setdefault("status", {})
            status["runtime_hardening"] = "v3.6.21"
            status["admission_conflict_probe"] = True
        return response

    execution_cls._execute_isolated_transfer = execute
    execution_cls._fallback_terminal_state = fallback
    execution_cls.api_organize_monitor_status = api_status
    setattr(execution_cls, _EXEC_PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.21】MoviePilot admission 精确冲突探针已启用："
        "宿主通用失败不再掩盖 TransferAdmissionConflictError，冲突成员直接 persistent blocked"
    )


__all__ = [
    "clear_admission_probe_v3621",
    "install_moviepilot_admission_probe_v3621",
    "install_admission_conflict_probe_v3621",
]
