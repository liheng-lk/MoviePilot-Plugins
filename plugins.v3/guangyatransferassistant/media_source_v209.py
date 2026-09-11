"""唯一 media_source 归一化：正确识别 MoviePilot 的 themoviedb / TMDB token。

禁止再用 ``"tmdb" in source``：对 ``themoviedb`` 会得到 False。
"""
from __future__ import annotations

from typing import Any, Optional


_TMDB_TOKENS = frozenset({
    "tmdb",
    "themoviedb",
    "themoviedb.org",
    "the movie db",
    "the movie database",
})


def _enum_raw(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "value"):
        try:
            return getattr(value, "value")
        except Exception:
            pass
    if hasattr(value, "name") and not isinstance(value, (str, bytes)):
        # MediaSource.TMDB → name "TMDB"
        try:
            name = getattr(value, "name")
            if isinstance(name, str) and name and name == name.upper() and len(name) <= 32:
                return name
        except Exception:
            pass
    return value


def _import_mp_normalize_media_source():
    """Prefer MoviePilot app.schemas.media; fallback to types. Only ImportError."""
    try:
        from app.schemas.media import normalize_media_source  # type: ignore
        return normalize_media_source
    except ImportError:
        pass
    try:
        from app.schemas.types import normalize_media_source  # type: ignore
        return normalize_media_source
    except ImportError:
        return None


def _import_mp_media_source_enum():
    try:
        from app.schemas.types import MediaSource  # type: ignore
        return MediaSource
    except ImportError:
        try:
            from app.schemas.media import MediaSource  # type: ignore
            return MediaSource
        except ImportError:
            return None


def normalize_media_source_token(value: Any) -> str:
    """把任意 media_source 归一成小写稳定 token；TMDB 家族统一为 ``tmdb``。"""
    if value is None:
        return ""

    MediaSource = _import_mp_media_source_enum()
    normalize_media_source = _import_mp_normalize_media_source()

    if MediaSource is not None:
        try:
            tmdb_enum = getattr(MediaSource, "TMDB", None)
            if tmdb_enum is not None and value == tmdb_enum:
                return "tmdb"
        except Exception:
            pass

    if callable(normalize_media_source):
        try:
            normalized = normalize_media_source(value)
            if MediaSource is not None:
                tmdb_enum = getattr(MediaSource, "TMDB", None)
                if tmdb_enum is not None and normalized == tmdb_enum:
                    return "tmdb"
            token = str(_enum_raw(normalized) or "").strip().lower()
            if token in _TMDB_TOKENS or token.replace("_", "") in {"tmdb", "themoviedb"}:
                return "tmdb"
            if token:
                return token
        except Exception:
            pass

    raw = _enum_raw(value)
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    # Exact / known aliases only — never broad ``"tmdb" in text``.
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    if text in _TMDB_TOKENS or compact in {"tmdb", "themoviedb", "themoviedb.org"}:
        return "tmdb"
    if compact == "imdb":
        return "imdb"
    if compact in {"douban", "db"}:
        return "douban"
    if compact in {"bangumi", "bgm"}:
        return "bangumi"
    if compact == "anilist":
        return "anilist"
    return text


def is_tmdb_source(value: Any) -> bool:
    """True iff value denotes TheMovieDB / TMDB media source."""
    return normalize_media_source_token(value) == "tmdb"


def is_imdb_source(value: Any) -> bool:
    return normalize_media_source_token(value) == "imdb"


__all__ = [
    "normalize_media_source_token",
    "is_tmdb_source",
    "is_imdb_source",
]
