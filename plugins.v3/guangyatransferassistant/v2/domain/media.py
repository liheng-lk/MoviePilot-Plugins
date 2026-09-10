"""媒体身份与缺集视图。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Set


@dataclass
class MediaIdentity:
    subscribe_id: int
    name: str
    year: Optional[int] = None
    season: Optional[int] = None
    media_source: str = ""
    media_id: str = ""
    is_movie: bool = False

    @classmethod
    def from_subscribe(cls, subscribe: Any, *, is_movie: bool = False) -> "MediaIdentity":
        year = getattr(subscribe, "year", None)
        try:
            year_i = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year_i = None
        season = getattr(subscribe, "season", None)
        try:
            season_i = int(season) if season not in (None, "") else None
        except (TypeError, ValueError):
            season_i = None
        return cls(
            subscribe_id=int(getattr(subscribe, "id", 0) or 0),
            name=str(getattr(subscribe, "name", "") or ""),
            year=year_i,
            season=season_i,
            media_source=str(getattr(subscribe, "media_source", "") or ""),
            media_id=str(getattr(subscribe, "media_id", "") or ""),
            is_movie=bool(is_movie),
        )


@dataclass
class MissingPlan:
    identity: MediaIdentity
    missing: Set[Any] = field(default_factory=set)
    reserved: Set[Any] = field(default_factory=set)
    claimed: Set[Any] = field(default_factory=set)

    @property
    def uncovered(self) -> Set[Any]:
        return set(self.missing) - set(self.reserved) - set(self.claimed)
