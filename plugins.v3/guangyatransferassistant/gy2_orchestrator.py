"""2.0 编排器：在旧流水线外包一层可解释匹配与轨迹。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .gy2_channel import ChannelAdapter
from .gy2_match import MatchEngine
from .gy2_media import MediaIdentity
from .gy2_naming import NamingPolicy
from .gy2_plan import WriteGate, order_candidates
from .gy2_trace import DecisionTraceStore


class TransferOrchestrator:
    """Discover → Match → Plan → Acquire(legacy) → Gate/Name/Trace。"""

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.matcher = MatchEngine()
        self.gate = WriteGate()
        self.namer = NamingPolicy()
        self.channel = ChannelAdapter()
        self.traces = DecisionTraceStore(plugin)

    def _is_movie(self, subscribe: Any) -> bool:
        checker = getattr(self.plugin, "_is_movie_subscription", None)
        if callable(checker):
            try:
                return bool(checker(subscribe))
            except Exception:
                return False
        return str(getattr(subscribe, "type", "") or "").lower() in {"movie", "movies", "电影"}

    def match_channel_entries(self, subscribe: Any, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        identity = MediaIdentity.from_subscribe(subscribe, is_movie=self._is_movie(subscribe))
        accepted: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        for entry in entries or []:
            result = self.matcher.match_entry(entry, identity)
            row = {
                "entry": entry,
                "result": result.as_dict(),
                "summary": self.channel.summarize_entry(entry),
            }
            if result.accepted:
                accepted.append(row)
            else:
                rejected.append(row)
                self.traces.append(
                    subscribe_id=identity.subscribe_id,
                    title=identity.name,
                    stage="match",
                    decision="reject",
                    reason_code=result.reason_code,
                    message=result.message,
                    details={"cleaned_title": result.cleaned_title, "message_id": entry.get("message_id")},
                )
        self.traces.append(
            subscribe_id=identity.subscribe_id,
            title=identity.name,
            stage="match",
            decision="summary",
            reason_code="ACCEPT" if accepted else "NO_MATCH",
            message=f"accepted={len(accepted)} rejected={len(rejected)}",
            details={"accepted": len(accepted), "rejected": len(rejected)},
        )
        return {"accepted": accepted, "rejected": rejected, "identity": identity}

    def evaluate_write_gate(
        self,
        *,
        subscribe: Any,
        library_missing: Optional[List[int]],
        logical_missing: List[int],
        reserved: Optional[List[int]] = None,
        claimed: Optional[List[int]] = None,
        physical_episodes: Optional[List[int]] = None,
        library_unavailable: bool = False,
        movie_done: bool = False,
    ) -> Dict[str, Any]:
        decision = self.gate.decide(
            library_missing=library_missing,
            logical_missing=logical_missing or [],
            reserved=reserved or [],
            claimed=claimed or [],
            physical_episodes=physical_episodes or [],
            library_unavailable=library_unavailable,
            is_movie=self._is_movie(subscribe),
            movie_done=movie_done,
        )
        identity = MediaIdentity.from_subscribe(subscribe, is_movie=self._is_movie(subscribe))
        self.traces.append(
            subscribe_id=identity.subscribe_id,
            title=identity.name,
            stage="write_gate",
            decision="accept" if decision.allowed else "reject",
            reason_code=decision.reason_code,
            message=decision.message,
            details=decision.as_dict(),
        )
        return decision.as_dict()

    def canonical_name(self, subscribe: Any, original: Any) -> str:
        return self.namer.canonical_name(subscribe, original, is_movie=self._is_movie(subscribe))

    def run_subscription(self, subscribe: Any, *, force: bool = False, refresh_channel: bool = True) -> Dict[str, Any]:
        """调用旧内核执行，并补写轨迹。"""
        identity = MediaIdentity.from_subscribe(subscribe, is_movie=self._is_movie(subscribe))
        self.traces.append(
            subscribe_id=identity.subscribe_id,
            title=identity.name,
            stage="acquire",
            decision="start",
            reason_code="START",
            message=f"force={bool(force)} refresh_channel={bool(refresh_channel)}",
        )
        # 必须走 legacy 入口，禁止再入 V2 包装（避免死循环）
        legacy = getattr(self.plugin, "_gy2_legacy_transfer_inner", None)
        if not callable(legacy):
            self.traces.append(
                subscribe_id=identity.subscribe_id,
                title=identity.name,
                stage="acquire",
                decision="error",
                reason_code="NO_LEGACY_RUNNER",
                message="旧流水线入口不可用",
            )
            return {"success": False, "message": "旧流水线入口不可用"}

        result = dict(legacy(subscribe, force=force, refresh_channel=refresh_channel) or {})
        self.traces.append(
            subscribe_id=identity.subscribe_id,
            title=identity.name,
            stage="receipt",
            decision="done" if result.get("success") or result.get("handled") else "incomplete",
            reason_code="DONE" if result.get("completed") else ("PENDING" if result.get("pending") else "INCOMPLETE"),
            message=str(result.get("message") or "")[:500],
            details={
                "success": bool(result.get("success")),
                "handled": bool(result.get("handled")),
                "completed": bool(result.get("completed")),
                "pending": bool(result.get("pending")),
            },
        )
        return result

    @staticmethod
    def prioritize(types: List[str]) -> List[str]:
        return order_candidates(types)
