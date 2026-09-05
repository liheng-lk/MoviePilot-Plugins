"""跨来源集级栅栏。

首轮实现只负责持久 reservation；后续接 MoviePilot 媒体库扫描后，把“已入库”也并入同一门禁。
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional


class EpisodeFence:
    DATA_KEY = "p115_episode_fence_v1"

    def __init__(self, load: Callable[[str], object], save: Callable[[str, object], object]):
        self._load = load
        self._save = save

    def _read(self) -> Dict[str, str]:
        raw = self._load(self.DATA_KEY) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    @staticmethod
    def key(tmdb_id: int, season: int, episode: int) -> str:
        return f"{int(tmdb_id)}:S{int(season):02d}:E{int(episode):03d}"

    def reserve(
        self,
        *,
        task_id: str,
        tmdb_id: Optional[int],
        season: Optional[int],
        episodes: Iterable[int],
    ) -> tuple[list[int], list[int]]:
        requested = sorted({int(ep) for ep in episodes if int(ep) > 0})
        if not tmdb_id or season is None or not requested:
            return requested, []
        data = self._read()
        accepted: list[int] = []
        blocked: list[int] = []
        for ep in requested:
            key = self.key(int(tmdb_id), int(season), ep)
            owner = str(data.get(key) or "")
            if owner and owner != task_id:
                blocked.append(ep)
                continue
            data[key] = task_id
            accepted.append(ep)
        self._save(self.DATA_KEY, data)
        return accepted, blocked

    def release(self, *, task_id: str, tmdb_id: Optional[int], season: Optional[int], episodes: Iterable[int]) -> None:
        if not tmdb_id or season is None:
            return
        data = self._read()
        changed = False
        for ep in episodes:
            key = self.key(int(tmdb_id), int(season), int(ep))
            if str(data.get(key) or "") == task_id:
                data.pop(key, None)
                changed = True
        if changed:
            self._save(self.DATA_KEY, data)

    def complete(self, *, task_id: str, tmdb_id: Optional[int], season: Optional[int], episodes: Iterable[int]) -> None:
        """完成后保留占用，避免同集再次被其它来源重复提交。"""
        if not tmdb_id or season is None:
            return
        data = self._read()
        for ep in episodes:
            key = self.key(int(tmdb_id), int(season), int(ep))
            data[key] = f"completed:{task_id}"
        self._save(self.DATA_KEY, data)
