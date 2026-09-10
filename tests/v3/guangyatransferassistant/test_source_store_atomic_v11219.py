from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PROVIDER = PLUGIN / "provider_reliability_v1100.py"


def _load_provider_module():
    package_name = "_gy_source_atomic_v11219_testpkg"
    pkg = types.ModuleType(package_name)
    pkg.__path__ = [str(PLUGIN)]
    sys.modules[package_name] = pkg

    if "requests" not in sys.modules:
        requests_stub = types.ModuleType("requests")
        requests_stub.Response = type("Response", (), {})
        requests_stub.Session = type("Session", (), {"__init__": lambda self: setattr(self, "proxies", {})})
        sys.modules["requests"] = requests_stub

    helper = types.ModuleType(f"{package_name}.provider_sources_v192")
    helper._proxy_dict = lambda _enabled: {}
    helper._dedupe_candidates = lambda rows: list(rows or [])
    helper._find_links = lambda *_args, **_kwargs: []
    sys.modules[helper.__name__] = helper

    spec = importlib.util.spec_from_file_location(f"{package_name}.provider_reliability_v1100", PROVIDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load_provider_module()


class _RacyStoreBase:
    def __init__(self, count: int = 24):
        self.rows = {f"s{index}": {"id": f"s{index}", "state": "new"} for index in range(count)}

    def _update_source(self, source_id: str, **fields):
        snapshot = {key: dict(value) for key, value in self.rows.items()}
        row = snapshot.get(source_id)
        if row is None:
            return None
        # 主动扩大旧实现的 read-modify-write 窗口；没有外层锁时会稳定丢写。
        time.sleep(0.002)
        row.update(fields)
        snapshot[source_id] = row
        self.rows = snapshot
        return dict(row)

    def _upsert_source(self, source_id: str, **fields):
        snapshot = {key: dict(value) for key, value in self.rows.items()}
        time.sleep(0.001)
        snapshot[source_id] = {"id": source_id, **fields}
        self.rows = snapshot
        # 模拟真实 cooperative 链内部可能再次走 update；要求外层必须是 RLock 而不是 Lock。
        return self._update_source(source_id, state=fields.get("state", "new"))

    def _delete_source(self, source_id: str):
        snapshot = {key: dict(value) for key, value in self.rows.items()}
        time.sleep(0.001)
        existed = snapshot.pop(source_id, None) is not None
        self.rows = snapshot
        return existed


class _Dummy(MOD.GuangYaProviderReliabilityV1100Mixin, _RacyStoreBase):
    pass


def test_concurrent_source_updates_do_not_overwrite_each_other():
    obj = _Dummy(24)
    threads = [
        threading.Thread(target=obj._update_source, args=(f"s{index}",), kwargs={"state": "completed"})
        for index in range(24)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert len(obj.rows) == 24
    assert all(row.get("state") == "completed" for row in obj.rows.values())


def test_source_mutation_lock_is_reentrant_for_nested_cooperative_updates():
    obj = _Dummy(0)
    result = obj._upsert_source("nested", state="queued")
    assert result["id"] == "nested"
    assert result["state"] == "queued"
    assert obj.rows["nested"]["state"] == "queued"


def test_delete_update_and_upsert_share_the_same_process_lock():
    text = PROVIDER.read_text(encoding="utf-8")
    assert "_SOURCE_STORE_MUTATION_LOCK_V11219 = threading.RLock()" in text
    upsert = text.split("    def _upsert_source(", 1)[1].split("    def _update_source(", 1)[0]
    update = text.split("    def _update_source(", 1)[1].split("    def _delete_source(", 1)[0]
    delete = text.split("    def _delete_source(", 1)[1].split("    def _parse_provider_defs(", 1)[0]
    for method in (upsert, update, delete):
        assert "with _SOURCE_STORE_MUTATION_LOCK_V11219:" in method
        assert "return super()." in method
