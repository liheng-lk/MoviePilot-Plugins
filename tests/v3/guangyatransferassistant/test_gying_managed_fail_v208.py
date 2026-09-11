"""2.0.8：GYING PoW 仍在链路；managed 失败不得 fallback native。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
ENTRY = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
POW = (PLUGIN / "gying_pow_v1111.py").read_text(encoding="utf-8")
PANSOU = (PLUGIN / "gying_pansou_v1110.py").read_text(encoding="utf-8")
ROUTING = (PLUGIN / "routing_v170.py").read_text(encoding="utf-8")


def test_gying_pow_stack_still_present_on_208():
    assert 'plugin_version = "2.0.9"' in ENTRY
    assert "class GuangYaGyingPowV1111Mixin" in POW
    assert "_gying_solve_challenge_v1110" in POW
    assert "_solve_pow_hex" in POW
    assert "challenge" in PANSOU.lower() or "_gying_solve_challenge" in PANSOU
    # 不走 115 / 不发明 bypass
    assert "115.com" not in POW.lower()
    assert "bypass" not in POW.lower()


def test_managed_failure_forces_handled_true_in_guard_one():
    body = ROUTING.split("def _guard_one_subscription(", 1)[1].split(
        "def _guard_subscribe_search(", 1
    )[0]
    assert 'result["handled"] = True' in body or "result['handled'] = True" in body
    assert "retryable" in body
    assert "禁止因光鸭失败回退原生" in body or "handled=True" in body
