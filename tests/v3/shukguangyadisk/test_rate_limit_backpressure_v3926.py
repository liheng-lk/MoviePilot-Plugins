from __future__ import annotations

import ast
import json
from pathlib import Path

from source_helper import single_init_plugin_path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = single_init_plugin_path(ROOT / "plugins.v3" / "shukguangyadisk")
NETWORK = (PLUGIN / "guangya_network_resilience_v347.py").read_text(encoding="utf-8")
WATCH = (PLUGIN / "organizer_watch_pipeline_v380.py").read_text(encoding="utf-8")


def _load_functions(source: str, *names: str) -> dict:
    tree = ast.parse(source)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict = {
        "Any": object,
        "Dict": dict,
        "_RATE_LIMIT_MARKERS": (
            "操作过于频繁",
            "请求过于频繁",
            "访问过于频繁",
            "too many requests",
            "rate limit",
            "rate_limit",
        ),
    }
    exec(compile(module, "<rate-limit-contract>", "exec"), namespace)
    return namespace


def test_http_200_business_rate_limit_is_transient_and_opens_long_circuit():
    namespace = _load_functions(
        NETWORK,
        "_rate_limited_text",
        "_rate_limited_result",
        "_transient_result",
    )
    rate_limited = namespace["_rate_limited_result"]
    transient = namespace["_transient_result"]

    response = {"code": 0, "msg": "操作过于频繁，请稍后重试"}
    assert rate_limited(response) is True
    assert transient(response) is True

    assert "_RATE_LIMIT_CIRCUIT_SECONDS = 300.0" in NETWORK
    assert 'result["rate_limited"] = True' in NETWORK
    assert "if _rate_limited_result(last_result):" in NETWORK
    assert "break" in NETWORK.split("if _rate_limited_result(last_result):", 1)[1].splitlines()[1]


def test_watch_scan_stops_current_batch_after_first_rate_limit_error():
    tree = ast.parse(WATCH)
    pulse = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_watch_pulse"
    )
    source = ast.get_source_segment(WATCH, pulse) or ""

    assert 'globals().get("_is_rate_limited_error")' in source
    assert "rate_limited_error_fn(err)" in source
    assert "rate_limited = True" in source
    assert "break" in source
    assert "watch_rate_limited=rate_limited" in source
    assert '"rate_limited": rate_limited' in source


def test_dispatch_defers_entire_queue_during_rate_limit_cooldown():
    assert "_global_rate_limit_remaining(plugin)" in WATCH
    assert '"reason": "rate_limit"' in WATCH
    assert "resource_dispatch_wait_reason=\"rate_limit\"" in WATCH
    assert "next_due" in WATCH


def test_v3927_release_metadata_is_atomic_and_new():
    package = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (ROOT / "plugins.v3" / "shukguangyadisk" / "plugin.json").read_text(encoding="utf-8")
    )
    entry = (PLUGIN / "__init__.py").read_text(encoding="utf-8")

    assert package["ShukGuangYaDisk"]["version"] == "3.9.27"
    assert manifest["version"] == "3.9.27"
    assert package["ShukGuangYaDisk"]["release"] is True
    assert "v3.9.27" in package["ShukGuangYaDisk"]["history"]
    assert "v3.9.27" in manifest["history"]
    assert 'plugin_version = "3.9.27"' in entry
