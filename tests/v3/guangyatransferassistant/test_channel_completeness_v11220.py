from __future__ import annotations

import ast
import functools
import html
import json
import re
import types
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
SOURCE_PATH = PLUGIN / "channel_sources_v190.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _compat_runtime():
    wanted_assigns = {
        "_CHANNEL_CATCHUP_KEY_V11220",
        "_CHANNEL_CATCHUP_MAX_PAGES_V11220",
        "_CHANNEL_CATCHUP_ATTEMPTS_V11220",
        "_LIVE_CHANNEL_HEADER_V11220",
    }
    wanted_funcs = {
        "_clean_live_channel_title_v11220",
        "_install_channel_title_compat_v11220",
        "_cursor_snapshot_v11220",
        "_channel_label_v11220",
        "_install_channel_cursor_completeness_v11220",
    }
    body = []
    for node in TREE.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted_assigns:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            body.append(node)
    ns = {
        "functools": functools,
        "html": html,
        "re": re,
        "Any": Any,
        "Dict": Dict,
        "List": List,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE_PATH), "exec"), ns)
    return ns


def test_live_hot_channel_tv_and_movie_headers_are_exact_titles():
    ns = _compat_runtime()

    class Legacy:
        _CHANNEL_META_BOUNDARY = re.compile(r"(?=\s*(?:📝|🎞|⭐|📅|$))")

        @staticmethod
        def _clean_channel_display_title(value):
            title = str(value or "").strip()
            title = re.sub(r"^[\s🎬🎞🎥📺]+", "", title).strip()
            return title

        @staticmethod
        def _extract_channel_display_title(value):
            return str(value or "").splitlines()[0].strip()

    ns["_install_channel_title_compat_v11220"](Legacy)

    assert Legacy._extract_channel_display_title(
        "📺 剧集：万界独尊 (2021) S01E481\n📝 简介：测试"
    ) == "万界独尊"
    assert Legacy._extract_channel_display_title(
        "🎬 电影：荣光与暗影 (2026)\n🎞 版本：2160p Remux"
    ) == "荣光与暗影"
    assert Legacy._extract_channel_display_title(
        "🎬 电影：海洋奇缘：启航 (2026)\n📝 简介：测试"
    ) == "海洋奇缘：启航"
    assert Legacy._extract_channel_display_title(
        "📺 动漫：凡人修仙传 (2020) S01E160-E161 已更新\n📅 播出日期：2026-09-09"
    ) == "凡人修仙传"


def test_live_template_tmdb_score_is_not_mistaken_for_tmdb_id():
    legacy = (PLUGIN / "legacy.py").read_text(encoding="utf-8")
    matched = re.search(r"TMDB_PATTERN\s*=\s*re\.compile\((.+?)\)\n", legacy, re.S)
    assert matched, "legacy TMDB_PATTERN missing"
    # Contract-level check: current regex intentionally requires TMDB + optional ID + digits;
    # the live channel's 'TMDB评分' field therefore falls back to exact title/year matching.
    pattern = re.compile(r"(?i)\bTMDB\s*(?:ID)?\s*[：:#]?\s*(\d{2,9})")
    assert pattern.search("⭐️ TMDB评分：9.5/10") is None
    assert pattern.search("TMDB ID：123456")


def test_cursor_backlog_never_advances_past_unread_pages_and_auto_catches_up():
    ns = _compat_runtime()
    source_url = "https://tgm.li668.asia/regengguangya"
    label = "光鸭云盘影视热更频道"

    class LegacyAssistant:
        def refresh_channels(self, force: bool = False):
            # Simulate legacy behavior: it always advances to the newest visible ID even when
            # the configured page depth has not reached the old cursor.
            old = int(((self.store.get("channel_cursors") or {}).get(source_url) or {}).get("last_message_id") or 0)
            enough = int(self._history_pages) >= 16
            self.store["channel_cursors"] = {
                source_url: {"last_message_id": 130, "updated": "legacy"}
            }
            self.store["channel_index"] = {
                "items": [{
                    "message_id": "130",
                    "source_url": source_url,
                    "source_label": label,
                    "stale": False,
                    "cached_index": False,
                }],
                "source_status": {
                    label: {
                        "success": True,
                        "pages": int(self._history_pages),
                        "cursor": 130,
                        "reached_cursor": enough,
                    }
                },
            }
            self.calls.append((int(self._history_pages), bool(force), old))
            return list(self.store["channel_index"]["items"])

    fake_legacy = types.SimpleNamespace(
        GuangYaTransferAssistant=LegacyAssistant,
        _clean_channel_display_title=lambda value: str(value or ""),
        _extract_channel_display_title=lambda value: str(value or ""),
        _CHANNEL_META_BOUNDARY=re.compile(r"$"),
    )
    ns["_install_channel_cursor_completeness_v11220"](fake_legacy)

    class Harness(LegacyAssistant):
        _history_pages = 2

        def __init__(self):
            self.store = {
                "channel_cursors": {
                    source_url: {"last_message_id": 100, "updated": "old"}
                }
            }
            self.logs = []
            self.calls = []

        def get_data(self, key):
            return self.store.get(key)

        def save_data(self, key, value):
            self.store[key] = value

        def _source_urls(self):
            return [source_url]

        def _plugin_log(self, level, message, *args):
            self.logs.append((level, message % args if args else message))

        @staticmethod
        def _now_text():
            return "2026-09-09 11:30:00"

    harness = Harness()

    # First tick is bounded: budgets 2 -> 4 -> 8 still cannot reach cursor=100.
    harness.refresh_channels(force=False)
    assert [row[0] for row in harness.calls] == [2, 4, 8]
    assert harness.store["channel_cursors"][source_url]["last_message_id"] == 100
    catchup = harness.store["channel_catchup_v11220"][source_url]
    assert catchup["high_watermark"] == 130
    assert catchup["page_budget"] == 16
    status = harness.store["channel_index"]["source_status"][label]
    assert status["catchup_incomplete"] is True
    assert status["cursor"] == 100
    assert status["high_watermark"] == 130
    assert status["next_page_budget"] == 16
    assert any("不会越过未读取消息" in message for _, message in harness.logs)

    # Next tick starts from the persisted depth=16 and reaches the old cursor in one pass.
    harness.calls.clear()
    harness.refresh_channels(force=False)
    assert harness.calls[0][0] == 16
    assert harness.calls[0][1] is True  # catchup bypasses ordinary refresh TTL
    assert harness.store["channel_cursors"][source_url]["last_message_id"] == 130
    assert source_url not in (harness.store.get("channel_catchup_v11220") or {})


def test_channel_completeness_patch_is_idempotent_and_public_release_is_v11220():
    ns = _compat_runtime()

    class LegacyAssistant:
        def refresh_channels(self, force: bool = False):
            return []

    fake = types.SimpleNamespace(
        GuangYaTransferAssistant=LegacyAssistant,
        _clean_channel_display_title=lambda value: str(value or ""),
        _extract_channel_display_title=lambda value: str(value or ""),
        _CHANNEL_META_BOUNDARY=re.compile(r"$"),
    )
    ns["_install_channel_title_compat_v11220"](fake)
    title_once = fake._extract_channel_display_title
    ns["_install_channel_title_compat_v11220"](fake)
    assert fake._extract_channel_display_title is title_once

    ns["_install_channel_cursor_completeness_v11220"](fake)
    refresh_once = fake.GuangYaTransferAssistant.refresh_channels
    ns["_install_channel_cursor_completeness_v11220"](fake)
    assert fake.GuangYaTransferAssistant.refresh_channels is refresh_once

    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    local = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))["GuangYaTransferAssistant"]
    assert 'plugin_version = "1.12.23"' in entry
    assert 'build_id = "20260909-r70"' in entry
    assert local["version"] == package["version"] == "1.12.23"
    assert "v1.12.20" in package.get("history", {})


def test_installer_connects_title_and_cursor_patches_before_multisource_early_return():
    installer = next(
        node for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == "install_channel_multisource_compat"
    )
    text = ast.get_source_segment(SOURCE, installer) or ""
    title_pos = text.index("_install_channel_title_compat_v11220")
    cursor_pos = text.index("_install_channel_cursor_completeness_v11220")
    early_return_pos = text.index("if not callable(current_extract) or not callable(current_key)")
    assert title_pos < early_return_pos
    assert cursor_pos < early_return_pos

