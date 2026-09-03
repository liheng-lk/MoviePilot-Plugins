import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = (ROOT / "plugins.v3/dailyassistant/__init__.py").read_text(encoding="utf-8")
PACKAGE = json.loads((ROOT / "package.v3.json").read_text(encoding="utf-8"))


def test_refresh_callback_args_use_func_kwargs_not_trigger_kwargs():
    assert '"func_kwargs": {"manual": True}' in ENTRY
    assert '"func_kwargs": {"manual": False}' in ENTRY
    assert '"kwargs": {"manual": True}' not in ENTRY
    assert '"kwargs": {"manual": False}' not in ENTRY


def test_once_service_places_run_date_in_trigger_kwargs():
    assert '"trigger": "date"' in ENTRY
    assert '"kwargs": {"run_date": datetime.datetime.now() + datetime.timedelta(seconds=3)}' in ENTRY


def test_interval_reconcile_still_uses_trigger_kwargs():
    hardening = (ROOT / "plugins.v3/dailyassistant/hardening_v110.py").read_text(encoding="utf-8")
    assert '"trigger": "interval"' in hardening
    assert '"kwargs": {"minutes": 5}' in hardening


def test_dailyassistant_market_version_is_v112():
    assert PACKAGE["DailyAssistant"]["version"] == "1.1.2"
    assert "v1.1.2" in PACKAGE["DailyAssistant"]["history"]
