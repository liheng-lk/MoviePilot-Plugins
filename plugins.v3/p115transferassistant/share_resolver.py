"""115 分享目录解析与安全文件选择。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from p115client.tool.iterdir import share_iter_files

from .episode_matcher import episode_intersection

VIDEO_EXTS = {
    ".mkv", ".mp4", ".ts", ".m2ts", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".rmvb"
}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
SKIP_WORDS = ("sample", "trailer", "preview", "花絮", "预告", "预覽", "预览")


@dataclass(slots=True)
class ShareResolvedFile:
    file_id: int
    name: str
    path: str
    size: int
    episodes: tuple[int, ...] = ()
    kind: str = "file"


@dataclass(slots=True)
class ShareResolveResult:
    file_ids: list[int] = field(default_factory=list)
    resolved_episodes: list[int] = field(default_factory=list)
    missing_episodes: list[int] = field(default_factory=list)
    files: list[ShareResolvedFile] = field(default_factory=list)
    ambiguous: dict[int, list[str]] = field(default_factory=dict)
    reason: str = ""

    @property
    def safe(self) -> bool:
        return bool(self.file_ids) and not self.missing_episodes and not self.ambiguous


def _normalize_file(item: dict[str, Any]) -> ShareResolvedFile:
    name = str(item.get("name") or item.get("n") or item.get("file_name") or "")
    path = str(item.get("path") or name)
    file_id = int(item.get("id") or item.get("fid") or item.get("file_id") or 0)
    size = int(item.get("size") or item.get("s") or 0)
    return ShareResolvedFile(file_id=file_id, name=name, path=path, size=size)


def _is_skip_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return any(word in lowered for word in SKIP_WORDS)


def resolve_share_files(
    client: Any,
    *,
    share_code: str,
    receive_code: str,
    target_episodes: Iterable[int] = (),
    season: int | None = None,
    media_type: str = "",
) -> ShareResolveResult:
    """递归读取分享文件并返回可安全转存的文件 ID。

    TV/动漫：只选目标缺集对应的视频及明确同集字幕；同一集出现多个视频版本时不猜。
    电影：仅在主视频唯一，或最大主视频显著大于其它候选时自动选择。
    """
    raw_files = list(
        share_iter_files(
            client=client,
            share_code=share_code,
            receive_code=receive_code,
            cid=0,
        )
    )
    files = [_normalize_file(item) for item in raw_files if isinstance(item, dict)]
    files = [item for item in files if item.file_id > 0 and item.name]

    targets = sorted({int(ep) for ep in target_episodes if int(ep) > 0})
    media_type_lower = str(media_type or "").lower()
    is_tv = bool(targets) or media_type_lower in {"tv", "电视剧", "动漫", "anime"}

    if is_tv:
        video_by_ep: dict[int, list[ShareResolvedFile]] = {ep: [] for ep in targets}
        subtitle_by_ep: dict[int, list[ShareResolvedFile]] = {ep: [] for ep in targets}

        for item in files:
            suffix = Path(item.name).suffix.lower()
            if suffix not in VIDEO_EXTS | SUBTITLE_EXTS or _is_skip_name(item.name):
                continue
            episodes = episode_intersection(item.name, targets, expected_season=season)
            if not episodes:
                episodes = episode_intersection(item.path, targets, expected_season=season)
            if not episodes:
                continue
            item.episodes = episodes
            bucket = video_by_ep if suffix in VIDEO_EXTS else subtitle_by_ep
            for episode in episodes:
                bucket.setdefault(episode, []).append(item)

        selected: dict[int, ShareResolvedFile] = {}
        ambiguous: dict[int, list[str]] = {}
        missing: list[int] = []
        for episode in targets:
            candidates = video_by_ep.get(episode) or []
            unique = {item.file_id: item for item in candidates}
            candidates = list(unique.values())
            if not candidates:
                missing.append(episode)
                continue
            if len(candidates) > 1:
                ambiguous[episode] = sorted(item.path for item in candidates)
                continue
            selected[episode] = candidates[0]

        chosen: dict[int, ShareResolvedFile] = {item.file_id: item for item in selected.values()}
        if not missing and not ambiguous:
            for episode in targets:
                for subtitle in subtitle_by_ep.get(episode) or []:
                    chosen[subtitle.file_id] = subtitle

        return ShareResolveResult(
            file_ids=sorted(chosen),
            resolved_episodes=sorted(selected),
            missing_episodes=missing,
            files=list(chosen.values()),
            ambiguous=ambiguous,
            reason=(
                "存在同集多个视频候选，拒绝自动猜版本" if ambiguous else
                "分享中未找到全部目标缺集" if missing else
                "已按缺集安全选择视频与字幕"
            ),
        )

    video_candidates = [
        item for item in files
        if Path(item.name).suffix.lower() in VIDEO_EXTS and not _is_skip_name(item.name)
    ]
    if not video_candidates:
        return ShareResolveResult(reason="分享中未找到主视频")
    video_candidates.sort(key=lambda item: item.size, reverse=True)
    chosen_video = video_candidates[0]
    if len(video_candidates) > 1:
        second = video_candidates[1]
        # 最大文件不足以明显区分时，可能是多版本/上下集，交给人工或后续质量策略。
        if chosen_video.size <= 0 or second.size >= chosen_video.size * 0.65:
            return ShareResolveResult(
                ambiguous={0: [item.path for item in video_candidates[:8]]},
                reason="电影分享存在多个接近体积的主视频候选",
            )

    chosen = {chosen_video.file_id: chosen_video}
    base_stem = Path(chosen_video.name).stem.lower()
    for item in files:
        if Path(item.name).suffix.lower() not in SUBTITLE_EXTS:
            continue
        stem = Path(item.name).stem.lower()
        if stem == base_stem or stem.startswith(base_stem + ".") or base_stem.startswith(stem + "."):
            chosen[item.file_id] = item

    return ShareResolveResult(
        file_ids=sorted(chosen),
        files=list(chosen.values()),
        reason="已选择电影主视频及明确关联字幕",
    )
