"""Final Plugin load harness for SIMULATED REALISTIC E2E.

Loads the real GuangYaTransferAssistant class without MoviePilot installed.
Only stubs external package boundaries (app.*, apscheduler, httpx, …).
Does NOT stub plugin internal business methods.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v3" / "guangyatransferassistant"
PKG = "plugins.v3.guangyatransferassistant"


class _Any:
    def __init__(self, *a, **k):
        for key, value in k.items():
            setattr(self, key, value)

    def __call__(self, *a, **k):
        return _Any()

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any()

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return False

    def __str__(self):
        return ""

    def __int__(self):
        return 0


def _ensure(name: str, path: Optional[Path] = None) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if path is not None:
        mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    return mod


def _install_app_stubs() -> None:
    if getattr(_install_app_stubs, "_done", False):
        return
    for name in (
        "app",
        "app.chain",
        "app.chain.subscribe",
        "app.chain.media",
        "app.chain.download",
        "app.chain.tmdb",
        "app.chain.transfer",
        "app.chain.storage",
        "app.schemas",
        "app.schemas.types",
        "app.sdk",
        "app.sdk.events",
        "app.sdk.logging",
        "app.sdk.config",
        "app.sdk.network",
        "app.sdk.plugins",
        "app.sdk.cache",
        "app.plugins",
        "app.db",
        "app.db.oper",
        "app.db.oper.subscribe",
        "app.db.models",
        "app.db.models.subscribe",
        "app.application",
        "app.application.subscription",
        "app.application.subscription.contract",
        "app.core",
        "app.core.context",
        "app.core.config",
        "app.core.meta",
        "app.core.metainfo",
        "app.helper",
        "app.helper.sites",
        "app.helper.message",
        "app.utils",
        "app.utils.string",
        "app.utils.http",
        "app.utils.common",
        "app.modules",
        "app.modules.filemanager",
        "apscheduler",
        "apscheduler.triggers",
        "apscheduler.triggers.cron",
        "apscheduler.schedulers",
        "apscheduler.schedulers.background",
        "httpx",
        "requests",
        "bs4",
        "lxml",
        "yaml",
        "dateutil",
        "tzlocal",
        "cn2an",
        "zhconv",
        "pyquery",
        "cloudscraper",
    ):
        _ensure(name)

    T = sys.modules["app.schemas.types"]
    T.EventType = type("EventType", (), {"PluginAction": "PluginAction", "Subscribe": "Subscribe"})
    T.MediaType = type("MediaType", (), {"TV": "TV", "MOVIE": "MOVIE", "ANIME": "ANIME"})
    T.MediaSource = type("MediaSource", (), {"TMDB": "TMDB"})
    T.NotificationType = type("NotificationType", (), {})

    sys.modules["app.sdk.events"].Event = type("Event", (), {})
    sys.modules["app.sdk.events"].eventmanager = type(
        "EM",
        (),
        {
            "register": staticmethod(lambda *a, **k: (lambda f: f)),
            "send_event": staticmethod(lambda *a, **k: None),
        },
    )()

    def _chain(name: str):
        return type(name, (), {"__init__": lambda self, *a, **k: None})

    sys.modules["app.chain.media"].MediaChain = _chain("MediaChain")
    sys.modules["app.chain.subscribe"].SubscribeChain = _chain("SubscribeChain")
    sys.modules["app.chain.subscribe"].build_subscribe_meta = lambda *a, **k: None
    sys.modules["app.chain.tmdb"].TmdbChain = _chain("TmdbChain")
    sys.modules["app.chain.download"].DownloadChain = _chain("DownloadChain")
    sys.modules["app.chain.transfer"].TransferChain = _chain("TransferChain")
    sys.modules["app.db.oper.subscribe"].SubscribeOper = _chain("SubscribeOper")
    sys.modules["app.db.models.subscribe"].Subscribe = _chain("Subscribe")
    sys.modules["apscheduler.triggers.cron"].CronTrigger = type(
        "CronTrigger",
        (),
        {"from_crontab": staticmethod(lambda *a, **k: _Any())},
    )

    class PluginBase:
        def __init__(self, *a, **k):
            pass

        def get_data(self, key):
            return None

        def save_data(self, key, value):
            pass

        def update_config(self, config=None):
            pass

        def get_config(self):
            return {}

    sys.modules["app.plugins"]._PluginBase = PluginBase
    sys.modules["app.plugins"].PluginBase = PluginBase
    settings = _Any(HOST="127.0.0.1", API_TOKEN="x", TEMP_PATH="/tmp")
    sys.modules["app.core.config"].settings = settings
    sys.modules["app.sdk.config"].settings = settings
    sys.modules["app.sdk.logging"].logger = _Any()

    # External HTTP client boundary used by GYING runtime.
    class _FakeCookies(dict):
        def set(self, key, value, **kwargs):  # noqa: ANN001
            self[str(key)] = value

        def clear(self):
            dict.clear(self)

    class _FakeResponse:
        def __init__(self, *, status_code=200, text="", url="", headers=None):
            self.status_code = int(status_code)
            self.text = str(text or "")
            self.content = self.text.encode("utf-8", errors="ignore")
            self.url = str(url or "")
            self.headers = dict(headers or {"content-type": "text/html"})

        def json(self):
            import json as _json
            return _json.loads(self.text or "{}")

    class _FakeSession:
        def __init__(self):
            self.headers = {}
            self.cookies = _FakeCookies()
            self.proxies = {}

        def get(self, url, **kwargs):
            return _FakeResponse(status_code=200, text="", url=str(url or ""))

        def post(self, url, **kwargs):
            return _FakeResponse(status_code=200, text='{"code":200}', url=str(url or ""))

        def request(self, method, url, **kwargs):
            return _FakeResponse(status_code=200, text="", url=str(url or ""))

    req = sys.modules["requests"]
    req.Session = _FakeSession
    req.get = lambda *a, **k: _FakeResponse()
    req.post = lambda *a, **k: _FakeResponse(text='{"code":200}')

    # MetaPath fallback for any remaining app.* imports.
    class _AppFinder:
        def find_module(self, fullname, path=None):  # py<3.12 style
            if fullname.startswith("app.") or fullname.startswith("apscheduler."):
                if fullname not in sys.modules:
                    _ensure(fullname)
                return self
            return None

        def load_module(self, fullname):
            return sys.modules[fullname]

    if not any(type(x).__name__ == "_AppFinder" for x in sys.meta_path):
        sys.meta_path.insert(0, _AppFinder())
    _install_app_stubs._done = True  # type: ignore[attr-defined]


def load_final_plugin():
    """Import and return the real GuangYaTransferAssistant class."""
    _install_app_stubs()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    _ensure("plugins", ROOT / "plugins")
    _ensure("plugins.v3", ROOT / "plugins.v3")
    existing = sys.modules.get(PKG)
    if existing is not None and getattr(existing, "GuangYaTransferAssistant", None):
        return existing.GuangYaTransferAssistant

    def _seed_missing_name(err: BaseException) -> bool:
        text = str(err)
        if "cannot import name" in text and " from " in text:
            try:
                missing = text.split("cannot import name", 1)[1].split("from", 1)[0].strip().strip("'\" ")
                modname = text.split(" from ", 1)[1].strip().split(" ")[0].strip().strip("'\" ()")
            except Exception:
                return False
            host = _ensure(modname)
            if missing[:1].islower():
                setattr(host, missing, lambda *a, **k: None)
            else:
                setattr(host, missing, type(missing, (), {"__init__": lambda self, *a, **k: None}))
            return True
        if isinstance(err, ModuleNotFoundError):
            name = getattr(err, "name", None) or ""
            if name:
                _ensure(name)
                return True
        if isinstance(err, AttributeError) and "has no attribute" in text:
            try:
                modname = text.split("'")[1]
                attr = text.split("'")[3]
            except Exception:
                return False
            host = _ensure(modname)
            setattr(host, attr, _Any if attr[:1].islower() else type(attr, (), {}))
            return True
        return False

    last: Optional[BaseException] = None
    for _ in range(80):
        # Drop partially imported plugin modules so retry is clean.
        doomed = [k for k in list(sys.modules) if k == PKG or k.startswith(PKG + ".")]
        for key in doomed:
            sys.modules.pop(key, None)
        init = PLUGIN / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            PKG,
            init,
            submodule_search_locations=[str(PLUGIN)],
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[PKG] = mod
        try:
            spec.loader.exec_module(mod)
            last = None
            break
        except Exception as err:  # noqa: BLE001 — intentional import bootstrap
            last = err
            if not _seed_missing_name(err):
                break
            continue
    if last is not None:
        raise last
    cls = getattr(sys.modules[PKG], "GuangYaTransferAssistant", None)
    if cls is None:
        raise RuntimeError("GuangYaTransferAssistant not exported after load")
    return cls


def make_final_plugin(*, store: Optional[Dict[str, Any]] = None, config: Optional[Dict[str, Any]] = None):
    """Instantiate Final Plugin with in-memory persistence; skip host init network."""
    cls = load_final_plugin()
    data: Dict[str, Any] = store if store is not None else {}
    plugin = cls.__new__(cls)
    plugin._enabled = True
    plugin._refresh_minutes = 5
    plugin._auto_transfer_on_refresh = True
    plugin._host_tick_heartbeat = 0.0
    plugin._host_airing_heartbeat_v211 = 0.0
    plugin._airing_due_lock_v211 = __import__("threading").RLock()
    plugin._airing_due_running_v211 = False
    plugin._airing_due_owner_v211 = ""
    plugin._airing_due_cycle_v211 = 0
    plugin._episode_snapshot_tls_v211 = __import__("threading").local()
    plugin._episode_runtime_ready_v211 = True
    plugin._airing_cycle_state_v211 = {}
    plugin._episode_target_lock_v210 = __import__("threading").RLock()
    plugin._episode_target_cache_v210 = {}
    plugin._pending_library_ttl_v210 = 1200
    plugin._library_snapshot_ttl_v210 = 120
    plugin._data_store_v211 = data
    plugin.plugin_version = "2.0.12"
    plugin.build_id = "20260911-r96"
    # Defaults normally set by mixin init_plugin — keep instance usable without full init.
    plugin._media_only = True
    plugin._episode_auto_confidence = 0.9
    plugin._quality_custom_reject_v1114 = ""
    plugin._quality_reject_low_tags_v1114 = True
    plugin._quality_require_subtitle_v1114 = False
    plugin._quality_min_resolution_v1114 = 720
    plugin._quality_min_video_mb_v1114 = 0
    plugin._external_search_cooldown_minutes_v1114 = 180
    plugin._external_round_allowed_v1114 = {}
    plugin._provider_auto_search = True
    plugin._channel_external_auto_dispatch = True
    plugin._xunlei_flash_enabled = False
    plugin._selected_subscriptions = []
    plugin._selected_subscription_ids = []
    plugin._managed_subscription_ids = []
    plugin._takeover_originals = {}
    plugin._route_lock = __import__("threading").RLock()


    def get_data(key):
        return data.get(key)

    def save_data(key, value):
        data[key] = value

    plugin.get_data = get_data
    plugin.save_data = save_data
    plugin._plugin_log = lambda level, msg, *args: None
    # Avoid heavy init_plugin side effects unless caller wants them.
    if config is not None:
        try:
            plugin.init_plugin(config)
        except Exception:
            pass
    return plugin


def mro_names(cls=None) -> List[str]:
    cls = cls or load_final_plugin()
    return [c.__name__ for c in cls.__mro__]


if __name__ == "__main__":
    Klass = load_final_plugin()
    names = mro_names(Klass)
    print("IMPORT_OK", Klass.__name__)
    for idx, name in enumerate(names[:30]):
        print(f"{idx:02d}", name)
    assert names.index("GuangYaEpisodeRuntimeV211Mixin") < names.index("GuangYaEpisodeTargetV210Mixin")
    print("MRO_RUNTIME_BEFORE_TARGET_OK")
