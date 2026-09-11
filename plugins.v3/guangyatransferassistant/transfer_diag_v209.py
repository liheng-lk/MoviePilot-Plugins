"""2.0.9：统一转存失败原因 / Resource Trace 诊断模型。"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


# Aggregate priority (higher wins for subscription-level summary).
_STATE_RANK = {
    "SUCCESS": 100,
    "PENDING": 80,
    "SKIPPED_COMPLETE": 65,
    "SKIPPED": 60,
    "FAILED_RETRYABLE": 40,
    "FAILED_FINAL": 20,
    "NO_RESULT": 10,
    "CONTINUE": 5,
}

STAGES = (
    "DISCOVERY",
    "MATCH",
    "LIBRARY_PREFLIGHT",
    "IDENTITY",
    "SHARE_INSPECT",
    "EPISODE_FENCE",
    "SOURCE_SELECTION",
    "SUBMIT",
    "REMOTE_VERIFY",
    "EXTERNAL_SEARCH",
    "COMPLETION",
)

REASON_NEXT_ACTION = {
    "CHANNEL_NO_ACTIONABLE_URL": "保留消息至 Inbox，等待解析器升级或其它协议资源",
    "CHANNEL_HIDDEN_URL_PARSE_FAILED": "保留原始 HTML；下一轮重试 decode/classify",
    "INBOX_WRITE_FAILED": "检查持久化存储后重试频道刷新",
    "NO_SUBSCRIPTION_MATCH": "等待新建托管订阅或标题/身份证据更新",
    "NO_LOCAL_RESOURCE": "等待频道/Inbox 出现匹配资源或主动检索补齐",
    "SELECTED_VIDEO_MISSING": "跳过该候选，等待含正片视频的其它来源",
    "REMOTE_VIDEO_MISSING": "云任务完成但无正片；允许其它候选接管",
    "SUBSCRIPTION_MATCH_REJECTED": "跳过该资源，继续寻找满足标题/年份/身份条件的候选",
    "LIBRARY_ALREADY_SATISFIED": "不再转存，进入官方订阅完成流程",
    "CURRENT_TARGET_ALREADY_SATISFIED": "保留订阅，等待未来应播窗口",
    "SUBSCRIPTION_COMPLETED": "无需动作",
    "PARTIAL_TRANSFER_PENDING": "本轮已确认部分文件，等待下轮继续转存剩余目标",
    "NO_NEW_ACTION": "无需动作",
    "TMDB_MATCH": "身份已确认，继续 Episode Fence / 提交",
    "TMDB_ID_MISMATCH": "拒绝该资源；等待正确 TMDB 标记的候选",
    "OFFICIAL_ALIAS_MATCH": "身份已确认，继续 Episode Fence / 提交",
    "TITLE_MATCH": "身份已确认，继续 Episode Fence / 提交",
    "MEDIA_IDENTITY_UNCONFIRMED": "等待带 TMDB/官方别名证据的新资源",
    "YEAR_MISMATCH": "跳过该资源，继续寻找正确年份候选",
    "SEASON_MISMATCH": "跳过该资源，继续寻找正确季",
    "SHARE_EXPIRED": "短 tombstone，并继续尝试同 ResourceGroup 其它候选",
    "SHARE_INSPECT_FAILED": "按子原因自动重试或换候选",
    "HTTP_TIMEOUT": "自动重试",
    "NETWORK_ERROR": "自动重试",
    "API_ERROR": "自动重试或换候选",
    "AUTH_ERROR": "检查光鸭登录态后重试",
    "MALFORMED_RESPONSE": "下一轮重试或换候选",
    "NO_SUPPORTED_MEDIA_FILES": "换其它候选来源",
    "EPISODE_NUMBER_UNRESOLVED": "等待更清晰文件名/结构的资源",
    "EPISODE_NOT_IN_ALLOWED_MISSING": "仅保留缺集子集；否则跳过",
    "RESOURCE_CONTAINS_ONLY_EXISTING_EPISODES": "无需转存",
    "FUTURE_EPISODE_NOT_DUE": "等待应播窗口",
    "TRANSFER_ALREADY_RESERVED": "等待现有任务完成",
    "SUPERSEDED_BY_HIGHER_PRIORITY_SOURCE": "无需动作",
    "SOURCE_CANDIDATE_INVALID": "跳过畸形候选",
    "CLOUD_TASK_SUBMIT_FAILED": "自动重试或换候选",
    "REMOTE_VERIFY_FAILED": "下一轮允许选择其它资源",
    "REMOTE_TASK_PENDING": "等待远端完成确认",
    "REMOTE_VERIFY_CONFIRMED": "无需动作",
    "XUNLEI_TRANSFER_CONFIRMED": "无需动作",
    "XUNLEI_ALREADY_PRESENT": "无需动作",
    "XUNLEI_TEMPLATE_BUILD_FAILED": "换候选或稍后重试",
    "EXTERNAL_SEARCH_NO_RESULT": "等待频道更新或稍后重试外部搜索",
    "EXTERNAL_SEARCH_NETWORK_ERROR": "自动重试",
    "PANSOU_POW_FAILED": "退避后重试 PoW",
    "NATIVE_FALLBACK_BLOCKED_BY_OWNERSHIP": "由 GuangYa 独占管理，不回退 native",
    "COMPLETION_SYNC_PENDING": "稍后重试官方 completion，不重新搜资源",
    "NO_LOCAL_RESOURCE": "等待频道资源到达或外部补搜",
    "TRANSFER_OK": "无需动作",
    "TRANSFER_FAILED": "查看候选级诊断后重试",
}

# Subscription-level reasons that may override candidate aggregation.
SUBSCRIPTION_LEVEL_REASON_CODES = frozenset({
    "SUBSCRIPTION_COMPLETED",
    "LIBRARY_ALREADY_SATISFIED",
    "CURRENT_TARGET_ALREADY_SATISFIED",
    "COMPLETION_SYNC_PENDING",
    "PARTIAL_TRANSFER_PENDING",
    "SUBSCRIPTION_CANCELLED",
    "NO_LOCAL_RESOURCE",
    "NO_NEW_ACTION",
})

_EXPIRED_TOKENS = (
    "失效", "不存在", "已删除", "已过期", "过期", "无效分享", "分享不存在",
    "expired", "deleted", "not found", "invalid share", "404",
)
_TIMEOUT_TOKENS = ("timeout", "timed out", "超时", "deadline exceeded")
_NETWORK_TOKENS = ("network", "connection", "连接", "dns", "reset by peer", "unreachable", "ssl")
_AUTH_TOKENS = ("认证", "登录", "authorization", "unauthorized", "401", "token 无效", "未登录")
_MALFORMED_TOKENS = ("malformed", "json", "decode", "parse", "空响应", "unexpected")


def stable_trace_id(*parts: Any) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:20]


def make_subscription_run_id(sid: Any, generation: Any = "", sequence: Any = 0) -> str:
    """Deterministic per-run id (no random)."""
    gen = str(generation or "").strip() or "0"
    seq = int(sequence or 0)
    return f"run:#{int(sid or 0)}:{gen}:{seq}"


def make_candidate_trace_id(source: str, identity: str = "", **extra: Any) -> str:
    src = str(source or "unknown").strip().lower() or "unknown"
    if src in {"guangya", "share"}:
        return f"guangya:{str(identity or extra.get('share_id') or '').strip()}"
    if src in {"xunlei", "xl"}:
        return f"xunlei:{str(identity or extra.get('share_id') or '').strip()}"
    if src == "magnet":
        btih = str(identity or extra.get("btih") or "").strip().upper()
        return f"magnet:{btih}"
    if src == "ed2k":
        file_hash = str(identity or extra.get("file_hash") or "").strip().lower()
        size = str(extra.get("size") or "").strip()
        return f"ed2k:{file_hash}:{size}" if size else f"ed2k:{file_hash}"
    return f"{src}:{str(identity or '').strip()}"


def make_diag(
    *,
    state: str,
    reason_code: str,
    stage: str,
    source: str = "",
    message: str = "",
    evidence: Optional[Dict[str, Any]] = None,
    next_action: str = "",
    trace_id: str = "",
    resource_trace_id: str = "",
    candidate_trace_id: str = "",
    subscription_run_id: str = "",
    sid: Any = None,
    terminal: Optional[bool] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    subscription_level: bool = False,
) -> Dict[str, Any]:
    code = str(reason_code or "")
    st = str(state or "")
    if terminal is None:
        terminal = st in {"SUCCESS", "FAILED_FINAL", "SKIPPED", "SKIPPED_COMPLETE", "NO_RESULT"} and code not in {
            "TMDB_MATCH", "OFFICIAL_ALIAS_MATCH", "TITLE_MATCH",
        }
        if st == "CONTINUE" or code in {"TMDB_MATCH", "OFFICIAL_ALIAS_MATCH", "TITLE_MATCH"}:
            terminal = False
        if st == "PENDING":
            terminal = False
    resource_id = str(resource_trace_id or trace_id or "")
    row = {
        "state": st,
        "reason_code": code,
        "stage": str(stage or ""),
        "source": str(source or ""),
        "message": str(message or "")[:400],
        "evidence": dict(evidence or {}),
        "next_action": str(next_action or REASON_NEXT_ACTION.get(code, ""))[:300],
        "trace_id": resource_id,
        "resource_trace_id": resource_id,
        "candidate_trace_id": str(candidate_trace_id or ""),
        "subscription_run_id": str(subscription_run_id or ""),
        "terminal": bool(terminal),
        "subscription_level": bool(subscription_level) or code in SUBSCRIPTION_LEVEL_REASON_CODES,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if sid is not None:
        try:
            row["sid"] = int(sid)
        except (TypeError, ValueError):
            row["sid"] = sid
    if candidates is not None:
        row["candidates"] = list(candidates)
    return row


def classify_share_inspect_failure(message: str, *, source: str = "guangya") -> Dict[str, Any]:
    text = str(message or "")
    low = text.lower()
    if any(token in text or token in low for token in _EXPIRED_TOKENS):
        code, state = "SHARE_EXPIRED", "FAILED_RETRYABLE"
    elif any(token in low or token in text for token in _TIMEOUT_TOKENS):
        code, state = "HTTP_TIMEOUT", "FAILED_RETRYABLE"
    elif any(token in low or token in text for token in _AUTH_TOKENS):
        code, state = "AUTH_ERROR", "FAILED_FINAL"
    elif any(token in low or token in text for token in _NETWORK_TOKENS):
        code, state = "NETWORK_ERROR", "FAILED_RETRYABLE"
    elif any(token in low or token in text for token in _MALFORMED_TOKENS):
        code, state = "MALFORMED_RESPONSE", "FAILED_RETRYABLE"
    elif "api" in low or "请求失败" in text or "读取分享" in text:
        code, state = "API_ERROR", "FAILED_RETRYABLE"
    else:
        code, state = "SHARE_INSPECT_FAILED", "FAILED_RETRYABLE"
    return make_diag(
        state=state,
        reason_code=code,
        stage="SHARE_INSPECT",
        source=source,
        message=text[:360],
        evidence={"raw_message": text[:200]},
    )


def identity_diag_from_assessment(
    assessment: Dict[str, Any],
    *,
    source: str = "guangya",
    resource_trace_id: str = "",
    candidate_trace_id: str = "",
    subscription_run_id: str = "",
    sid: Any = None,
) -> Dict[str, Any]:
    code = str(assessment.get("reason_code") or assessment.get("reason") or "MEDIA_IDENTITY_UNCONFIRMED")
    ok = bool(assessment.get("ok"))
    if code in {"TMDB_MATCH", "OFFICIAL_ALIAS_MATCH", "TITLE_MATCH"} or ok:
        state = "CONTINUE"
        terminal = False
    else:
        state = str(assessment.get("state") or "FAILED_FINAL")
        terminal = True
    return make_diag(
        state=state,
        reason_code=code,
        stage=str(assessment.get("stage") or "IDENTITY"),
        source=source,
        message=str(assessment.get("message") or assessment.get("reason") or code)[:360],
        evidence=dict(assessment.get("evidence") or {}),
        resource_trace_id=resource_trace_id,
        candidate_trace_id=candidate_trace_id,
        subscription_run_id=subscription_run_id,
        sid=sid,
        terminal=terminal,
    )


def classify_transfer_message_v209(result: Dict[str, Any], subscribe: Any = None) -> Dict[str, Any]:
    """Legacy fallback only — never override an existing structured diag."""
    if isinstance((result or {}).get("diag"), dict) and (result.get("diag") or {}).get("reason_code"):
        return dict(result["diag"])
    if isinstance((result or {}).get("candidate_diags"), list) and result.get("candidate_diags"):
        return aggregate_subscription_diag(list(result["candidate_diags"]))

    message = str((result or {}).get("message") or "")
    sid = int(getattr(subscribe, "id", 0) or 0) if subscribe is not None else 0
    title = str(getattr(subscribe, "name", "") or "") if subscribe is not None else ""
    evidence = {"subscribe_id": sid, "subscribe_title": title}
    run_id = str((result or {}).get("subscription_run_id") or "")
    resource_trace = str((result or {}).get("resource_trace_id") or "")

    def _wrap(**kwargs: Any) -> Dict[str, Any]:
        kwargs.setdefault("evidence", evidence)
        kwargs.setdefault("subscription_run_id", run_id)
        kwargs.setdefault("resource_trace_id", resource_trace)
        kwargs.setdefault("sid", sid)
        return make_diag(**kwargs)

    # Prefer completion / already / pending BEFORE raw success.
    if bool((result or {}).get("completed")):
        return _wrap(state="SUCCESS", reason_code="SUBSCRIPTION_COMPLETED", stage="COMPLETION", message=message or "订阅已完成")
    if bool((result or {}).get("completion_pending")):
        return _wrap(state="PENDING", reason_code="COMPLETION_SYNC_PENDING", stage="COMPLETION", message=message or "目标已满足但订阅完成同步待重试")
    if bool((result or {}).get("pending")):
        return _wrap(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="REMOTE_VERIFY", message=message or "云任务等待确认")
    if bool((result or {}).get("busy")):
        return _wrap(state="PENDING", reason_code="TRANSFER_ALREADY_RESERVED", stage="SOURCE_SELECTION", message=message or "已有同媒体任务执行中")
    if bool((result or {}).get("already")):
        if "满足" in message or "satisfied" in message.lower():
            return _wrap(state="SKIPPED", reason_code="CURRENT_TARGET_ALREADY_SATISFIED", stage="LIBRARY_PREFLIGHT", message=message or "当前目标已满足")
        if "无新增" in message or "已同步" in message or "没有新链接" in message:
            return _wrap(state="SKIPPED", reason_code="NO_NEW_ACTION", stage="EPISODE_FENCE", message=message or "已同步，无新增资源")
        return _wrap(state="SKIPPED", reason_code="TRANSFER_ALREADY_RESERVED", stage="SOURCE_SELECTION", message=message or "已处理/已有任务")
    if "暂未匹配" in message or "本地频道索引暂未匹配" in message:
        return _wrap(state="NO_RESULT", reason_code="NO_LOCAL_RESOURCE", stage="MATCH", message=message or "本地频道暂无匹配资源")
    if "匹配分享均不可用" in message:
        return _wrap(
            state="FAILED_RETRYABLE",
            reason_code="SHARE_INSPECT_FAILED",
            stage="SHARE_INSPECT",
            message="候选分享均不可用（需查看子候选 trace 获取具体原因）",
            next_action="检查各候选 SHARE_EXPIRED / INSPECT / EPISODE 诊断，勿只看汇总句",
        )
    if bool((result or {}).get("success")) and ("入队" in message or "云" in message or "任务" in message or "等待" in message):
        return _wrap(state="PENDING", reason_code="REMOTE_TASK_PENDING", stage="SUBMIT", message=message or "云任务已提交")
    if bool((result or {}).get("success")):
        return _wrap(state="SUCCESS", reason_code="TRANSFER_OK", stage="SUBMIT", message=message or "转存成功")
    return _wrap(
        state="FAILED_RETRYABLE",
        reason_code="TRANSFER_FAILED",
        stage="SUBMIT",
        message=message or "转存未完成",
        next_action="查看同订阅候选级 trace_id 获取真实阶段原因",
    )


def aggregate_subscription_diag(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    usable = [dict(row) for row in (rows or []) if isinstance(row, dict)]
    # CONTINUE / non-terminal identity confirmations do not win aggregation alone.
    actionable = [
        row for row in usable
        if str(row.get("state") or "") not in {"CONTINUE"} and str(row.get("reason_code") or "") not in {
            "TMDB_MATCH", "OFFICIAL_ALIAS_MATCH", "TITLE_MATCH",
        }
    ]
    pool = actionable or usable
    if not pool:
        return make_diag(
            state="NO_RESULT",
            reason_code="NO_LOCAL_RESOURCE",
            stage="MATCH",
            message="无候选诊断",
        )
    best = max(pool, key=lambda r: _STATE_RANK.get(str(r.get("state") or ""), 0))
    out = dict(best)
    summaries = []
    for row in usable:
        summaries.append({
            "source": str(row.get("source") or ""),
            "reason": str(row.get("reason_code") or ""),
            "state": str(row.get("state") or ""),
            "candidate_trace_id": str(row.get("candidate_trace_id") or ""),
            "resource_trace_id": str(row.get("resource_trace_id") or row.get("trace_id") or ""),
            "stage": str(row.get("stage") or ""),
        })
    out["candidates"] = summaries
    out["final_state"] = str(out.get("state") or "")
    out["final_reason"] = str(out.get("reason_code") or "")
    # Prefer carried subscription_run_id / resource_trace_id from any row.
    if not out.get("subscription_run_id"):
        for row in usable:
            if row.get("subscription_run_id"):
                out["subscription_run_id"] = row["subscription_run_id"]
                break
    if not out.get("resource_trace_id"):
        for row in usable:
            rid = row.get("resource_trace_id") or row.get("trace_id")
            if rid:
                out["resource_trace_id"] = rid
                out["trace_id"] = rid
                break
    return out


def candidate_diag_key(row: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    return (
        str(row.get("subscription_run_id") or ""),
        str(row.get("resource_trace_id") or row.get("trace_id") or ""),
        str(row.get("candidate_trace_id") or ""),
        str(row.get("stage") or ""),
        str(row.get("reason_code") or ""),
        str(row.get("state") or ""),
    )


def dedup_candidate_diags(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep one row per (run, resource, candidate, stage, reason, state)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = candidate_diag_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def is_subscription_level_diag(diag: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(diag, dict):
        return False
    code = str(diag.get("reason_code") or "")
    if code in SUBSCRIPTION_LEVEL_REASON_CODES:
        return True
    # Explicit flag from producers.
    return bool(diag.get("subscription_level"))


def finalize_subscription_diag(
    *,
    candidate_diags: Optional[Sequence[Dict[str, Any]]] = None,
    result_diag: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    subscribe: Any = None,
) -> Dict[str, Any]:
    """Candidate aggregation is authoritative unless a true subscription-level override exists."""
    rows = dedup_candidate_diags(list(candidate_diags or []))
    aggregated = aggregate_subscription_diag(rows) if rows else None
    override = result_diag if is_subscription_level_diag(result_diag) else None
    if override is None and isinstance(result, dict):
        # Promote partial / completion flags from result payload.
        if bool(result.get("partial")) or str(result.get("reason_code") or "") == "PARTIAL_TRANSFER_PENDING":
            override = make_diag(
                state="PENDING",
                reason_code="PARTIAL_TRANSFER_PENDING",
                stage="COMPLETION",
                message=str(result.get("message") or "部分转存完成，剩余等待下轮"),
                evidence={
                    "new_count": result.get("new_count"),
                    "remaining": result.get("remaining"),
                },
                subscription_run_id=str(result.get("subscription_run_id") or ""),
                sid=getattr(subscribe, "id", None) if subscribe is not None else result.get("sid"),
                subscription_level=True,
            )
        elif bool(result.get("completed")):
            override = make_diag(
                state="SUCCESS",
                reason_code="SUBSCRIPTION_COMPLETED",
                stage="COMPLETION",
                message=str(result.get("message") or "订阅已完成"),
                subscription_run_id=str(result.get("subscription_run_id") or ""),
                sid=getattr(subscribe, "id", None) if subscribe is not None else None,
            )
            override["subscription_level"] = True
        elif bool(result.get("completion_pending")):
            override = make_diag(
                state="PENDING",
                reason_code="COMPLETION_SYNC_PENDING",
                stage="COMPLETION",
                message=str(result.get("message") or "completion pending"),
                subscription_run_id=str(result.get("subscription_run_id") or ""),
                sid=getattr(subscribe, "id", None) if subscribe is not None else None,
            )
            override["subscription_level"] = True
    if override is not None:
        final = dict(override)
        if aggregated:
            final.setdefault("candidates", aggregated.get("candidates") or [])
        final["final_state"] = str(final.get("state") or "")
        final["final_reason"] = str(final.get("reason_code") or "")
        return final
    if aggregated is not None:
        return aggregated
    if isinstance(result_diag, dict) and result_diag.get("reason_code"):
        return dict(result_diag)
    return classify_transfer_message_v209(dict(result or {}), subscribe)


def format_diag_log(diag: Dict[str, Any], *, media: str = "") -> str:
    """Single-line human log without secrets."""
    evidence = diag.get("evidence") or {}
    safe_evidence = {
        k: v for k, v in evidence.items()
        if str(k).lower() not in {"pwd", "passcode", "password", "cookie", "token", "access_token"}
    }
    if "passcode" in evidence or "pwd" in evidence:
        safe_evidence["passcode_present"] = True
    return (
        f"【转存诊断】media={media or safe_evidence.get('subscribe_title') or '-'} "
        f"run={str(diag.get('subscription_run_id') or '-')[:40]} "
        f"stage={diag.get('stage') or '-'} state={diag.get('state') or '-'} "
        f"reason={diag.get('reason_code') or '-'} source={diag.get('source') or '-'} "
        f"resource={str(diag.get('resource_trace_id') or diag.get('trace_id') or '-')[:80]} "
        f"candidate={str(diag.get('candidate_trace_id') or '-')[:80]} "
        f"msg={str(diag.get('message') or '-')[:180]} "
        f"next={str(diag.get('next_action') or '-')[:120]} "
        f"evidence={safe_evidence}"
    )


def batch_summary_buckets(diags: List[Dict[str, Any]]) -> Dict[str, int]:
    buckets = {
        "checked": len(diags),
        "success": 0,
        "pending": 0,
        "completed": 0,
        "satisfied": 0,
        "no_need": 0,
        "no_local": 0,
        "expired": 0,
        "identity_reject": 0,
        "season_conflict": 0,
        "external_empty": 0,
        "network": 0,
        "failed": 0,
    }
    for diag in diags or []:
        code = str(diag.get("reason_code") or "")
        state = str(diag.get("state") or "")
        if code == "SUBSCRIPTION_COMPLETED":
            buckets["completed"] += 1
        elif state == "SUCCESS" or code in {"TRANSFER_OK", "REMOTE_VERIFY_CONFIRMED", "XUNLEI_TRANSFER_CONFIRMED"}:
            buckets["success"] += 1
        elif state == "PENDING" or code in {
            "REMOTE_TASK_PENDING", "COMPLETION_SYNC_PENDING", "TRANSFER_ALREADY_RESERVED",
            "PARTIAL_TRANSFER_PENDING",
        }:
            buckets["pending"] += 1
        elif code in {
            "LIBRARY_ALREADY_SATISFIED",
            "CURRENT_TARGET_ALREADY_SATISFIED",
        }:
            buckets["satisfied"] += 1
        elif code in {
            "RESOURCE_CONTAINS_ONLY_EXISTING_EPISODES",
            "FUTURE_EPISODE_NOT_DUE",
            "SUPERSEDED_BY_HIGHER_PRIORITY_SOURCE",
            "NO_NEW_ACTION",
            "EPISODE_NOT_IN_ALLOWED_MISSING",
        }:
            buckets["no_need"] += 1
        elif code in {"NO_LOCAL_RESOURCE", "NO_SUBSCRIPTION_MATCH", "CHANNEL_NO_ACTIONABLE_URL"}:
            buckets["no_local"] += 1
        elif code == "SHARE_EXPIRED":
            buckets["expired"] += 1
        elif code == "SEASON_MISMATCH":
            buckets["season_conflict"] += 1
        elif code in {"TMDB_ID_MISMATCH", "MEDIA_IDENTITY_UNCONFIRMED", "SUBSCRIPTION_MATCH_REJECTED", "YEAR_MISMATCH"}:
            buckets["identity_reject"] += 1
        elif code == "EXTERNAL_SEARCH_NO_RESULT":
            buckets["external_empty"] += 1
        elif code in {"EXTERNAL_SEARCH_NETWORK_ERROR", "HTTP_TIMEOUT", "NETWORK_ERROR"}:
            buckets["network"] += 1
        elif state.startswith("FAILED") or code in {
            "CLOUD_TASK_SUBMIT_FAILED", "REMOTE_VERIFY_FAILED", "TRANSFER_FAILED",
            "AUTH_ERROR", "API_ERROR",
        }:
            buckets["failed"] += 1
        else:
            buckets["no_local"] += 1
    return buckets


def format_batch_summary(buckets: Dict[str, int], highlights: Optional[List[str]] = None) -> str:
    lines = [
        "⚠️ 光鸭转存检查汇总",
        f"本轮检查：{buckets.get('checked', 0)}",
        f"成功转存：{buckets.get('success', 0)}",
        f"等待云任务：{buckets.get('pending', 0)}",
        f"订阅已完成：{buckets.get('completed', 0)}",
        f"媒体库已满足：{buckets.get('satisfied', 0)}",
        f"当前无需转存：{buckets.get('no_need', 0)}",
        f"本地暂无资源：{buckets.get('no_local', 0)}",
        f"资源失效：{buckets.get('expired', 0)}",
        f"身份验证未通过：{buckets.get('identity_reject', 0)}",
        f"季/集冲突：{buckets.get('season_conflict', 0)}",
        f"外部搜索无结果：{buckets.get('external_empty', 0)}",
        f"临时网络错误：{buckets.get('network', 0)}",
        f"真正失败：{buckets.get('failed', 0)}",
    ]
    if highlights:
        lines.append("重点异常：")
        lines.extend(highlights[:8])
    return "\n".join(lines)


def enrich_diag(
    diag: Dict[str, Any],
    *,
    subscription_run_id: str = "",
    resource_trace_id: str = "",
    candidate_trace_id: str = "",
    sid: Any = None,
) -> Dict[str, Any]:
    out = dict(diag or {})
    if subscription_run_id and not out.get("subscription_run_id"):
        out["subscription_run_id"] = subscription_run_id
    rid = resource_trace_id or out.get("resource_trace_id") or out.get("trace_id") or ""
    if rid:
        out["resource_trace_id"] = rid
        out["trace_id"] = rid
    if candidate_trace_id and not out.get("candidate_trace_id"):
        out["candidate_trace_id"] = candidate_trace_id
    if sid is not None and out.get("sid") in (None, "", 0):
        try:
            out["sid"] = int(sid)
        except (TypeError, ValueError):
            out["sid"] = sid
    return out


__all__ = [
    "STAGES",
    "REASON_NEXT_ACTION",
    "SUBSCRIPTION_LEVEL_REASON_CODES",
    "make_diag",
    "make_subscription_run_id",
    "make_candidate_trace_id",
    "classify_share_inspect_failure",
    "identity_diag_from_assessment",
    "classify_transfer_message_v209",
    "aggregate_subscription_diag",
    "candidate_diag_key",
    "dedup_candidate_diags",
    "is_subscription_level_diag",
    "finalize_subscription_diag",
    "format_diag_log",
    "batch_summary_buckets",
    "format_batch_summary",
    "stable_trace_id",
    "enrich_diag",
]
