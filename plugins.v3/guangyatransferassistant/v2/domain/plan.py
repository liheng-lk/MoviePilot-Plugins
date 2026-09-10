"""写盘门禁与来源优先级规划。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Set


SOURCE_PRIORITY = ("xunlei", "guangya", "magnet", "ed2k")


@dataclass
class WriteDecision:
    allowed: bool
    reason_code: str
    allowed_episodes: Set[int]
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "allowed_episodes": sorted(self.allowed_episodes),
            "message": self.message,
        }


class WriteGate:
    """权威缺集 ∩ 未 claim − reservation；物理文件集必须 ⊆ allowed。"""

    def decide(
        self,
        *,
        library_missing: Optional[Iterable[int]],
        logical_missing: Iterable[int],
        reserved: Iterable[int] = (),
        claimed: Iterable[int] = (),
        physical_episodes: Iterable[int] = (),
        library_unavailable: bool = False,
        is_movie: bool = False,
        movie_done: bool = False,
    ) -> WriteDecision:
        if is_movie:
            if movie_done:
                return WriteDecision(False, "ALREADY_COVERED", set(), "电影已完成")
            return WriteDecision(True, "ACCEPT", set(), "允许电影写入")

        if library_unavailable:
            return WriteDecision(False, "LIBRARY_UNAVAILABLE", set(), "媒体库缺集事实不可用，fail-closed")

        logical = {int(x) for x in logical_missing if int(x) > 0}
        reserved_set = {int(x) for x in reserved if int(x) > 0}
        claimed_set = {int(x) for x in claimed if int(x) > 0}
        if library_missing is None:
            allowed = set(logical)
        else:
            library = {int(x) for x in library_missing if int(x) > 0}
            allowed = library & logical
        allowed -= reserved_set
        allowed -= claimed_set
        if not allowed:
            return WriteDecision(False, "ALREADY_COVERED", set(), "无剩余可写缺集")

        physical = {int(x) for x in physical_episodes if int(x) > 0}
        if physical and not physical.issubset(allowed):
            return WriteDecision(
                False,
                "PHYSICAL_OVERFLOW",
                allowed,
                f"物理集号越界 physical={sorted(physical)} allowed={sorted(allowed)}",
            )
        return WriteDecision(True, "ACCEPT", allowed, "通过写盘门禁")


def order_candidates(candidate_types: Sequence[str]) -> List[str]:
    rank = {name: index for index, name in enumerate(SOURCE_PRIORITY)}
    unique = []
    seen = set()
    for item in candidate_types:
        key = str(item or "").strip().lower()
        if key in {"guangya_share", "share"}:
            key = "guangya"
        if key in {"xunlei_flash", "flash"}:
            key = "xunlei"
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(key)
    return sorted(unique, key=lambda name: rank.get(name, 99))
