import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
RUNTIME = ROOT / "plugins.v3" / "guangyatransferassistant" / "runtime_v170.py"

entry_text = ENTRY.read_text(encoding="utf-8")
runtime_text = RUNTIME.read_text(encoding="utf-8")


def test_runtime_finalizer_is_wired_first_and_syntax_valid():
    ast.parse(entry_text)
    ast.parse(runtime_text)
    assert "from .runtime_v170 import GuangYaRuntimeFinalizerMixin" in entry_text
    assert "GuangYaRuntimeFinalizerMixin," in entry_text
    assert 'build_id = "20260824-r7"' in runtime_text


def test_scheduler_takeover_is_nonblocking_for_guangya_routes():
    block = runtime_text.split("    def _dispatch_subscribe_search", 1)[1].split("    def _try_transfer_subscription", 1)[0]
    assert "self._queue_async_route_check([current_sid]" in block
    assert "self._queue_async_route_check(route_ids" in block
    assert "_try_transfer_subscription" not in block
    assert "SubscribeChain().search" in block
    assert "已阻断原生搜索并转入后台光鸭检查" in block


def test_periodic_processing_only_queues_background_work():
    block = runtime_text.split("    def _process_selected_subscriptions", 1)[1].split("    def _dispatch_subscribe_search", 1)[0]
    assert "self._queue_async_route_check(ids" in block
    assert "_try_transfer_subscription" not in block
    assert '"queued": True' in block


def test_old_hot_reload_instance_cannot_start_network_or_transfer_work():
    assert "if hasattr(self, \"_runtime_generation\") and not self._runtime_is_current():" in runtime_text
    assert "def _startup_check" in runtime_text and "not self._runtime_is_current()" in runtime_text
    assert "def _tick" in runtime_text
    transfer = runtime_text.split("    def _try_transfer_subscription", 1)[1].split("    def _diagnose_subscription", 1)[0]
    assert "if not self._runtime_is_current():" in transfer
    assert '"stale_instance": True' in transfer


def test_runtime_worker_exits_when_stable_owner_changes():
    block = runtime_text.split("    def _runtime_worker_loop", 1)[1].split("    def _startup_check", 1)[0]
    assert "while self._enabled and self._runtime_is_current():" in block
    assert "if not self._runtime_is_current() or not self._enabled:" in block
    assert "generation == type(self)._runtime_generation" not in block


def test_takeover_chain_is_unwrapped_to_real_moviepilot_callback():
    unwrap = runtime_text.split("    def _unwrap_takeover_original", 1)[1].split("    def _install_takeover", 1)[0]
    install = runtime_text.split("    def _install_takeover", 1)[1].split("    def refresh_channels", 1)[0]
    assert 'mapping = getattr(owner, "_takeover_originals", None)' in unwrap
    assert "candidate = mapping.get(job_id)" in unwrap
    assert "self._takeover_originals[job_id] = unwrapped" in install
    assert "追溯到 MoviePilot 原调度函数" in install


def test_channel_recovery_timer_releases_slot_before_retry():
    block = runtime_text.split("    def _schedule_channel_recovery", 1)[1].split("    def _unwrap_takeover_original", 1)[0]
    assert "if self._channel_recovery_timer is timer:" in block
    assert "self._channel_recovery_timer = None" in block
    assert block.index("self._channel_recovery_timer = None") < block.index("self._queue_async_route_check")
    assert 'trigger="频道故障自动恢复"' in block


def test_diagnosis_uses_real_media_fact_key_for_jobs():
    block = runtime_text.split("    def _diagnose_subscription", 1)[1]
    assert "prefix = self._media_fact_prefix(subscribe)" in block
    assert 'str(item.get("media") or "") == str(prefix)' in block
    assert 'pending_status = {"submitting", "submitted", "task_confirmed", "verifying"}' in block
    assert "正在等待光鸭落盘确认" in block


def test_guard_health_is_attached_by_title_not_blind_first_card():
    page = entry_text.split("    def get_page", 1)[1]
    assert 'str(props.get("title") or "") == "固定分流路由健康"' in page
    assert "health_card = page" in page
    assert "health_card[\"props\"] = props" in page
    assert "pages[0][\"props\"] = props" not in page
