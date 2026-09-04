from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / 'plugins.v3' / 'shukguangyadisk'
FLOOR = (3, 6, 18)


def _json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _version(value: object) -> tuple[int, ...]:
    text = str(value or '').strip().lstrip('v')
    parts = text.split('.')
    assert parts and all(part.isdigit() for part in parts), text
    return tuple(int(part) for part in parts)


def test_v3617_release_floor_prevents_normal_ci_version_rollback():
    plugin_version = _version(_json(PLUGIN / 'plugin.json')['version'])
    market_version = _version(_json(ROOT / 'package.v3.json')['ShukGuangYaDisk']['version'])
    entry = (PLUGIN / '__init__.py').read_text(encoding='utf-8')
    remote = (PLUGIN / 'dist' / 'assets' / 'remoteEntry.js').read_text(encoding='utf-8')
    match = re.search(r'plugin_version\s*=\s*["\']([^"\']+)', entry)
    assert match, 'plugin_version not found'
    entry_version = _version(match.group(1))
    cache = re.search(r'AssistantPage-v352\.js\?v=([0-9.]+)', remote)
    assert cache, 'AssistantPage cache version not found'
    cache_version = _version(cache.group(1))
    assert plugin_version >= FLOOR
    assert market_version >= FLOOR
    assert entry_version >= FLOOR
    assert cache_version >= FLOOR
    assert plugin_version == market_version == entry_version == cache_version
