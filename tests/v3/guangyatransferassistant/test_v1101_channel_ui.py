import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins.v3" / "guangyatransferassistant" / "channel_ui_v1101.py"
spec = importlib.util.spec_from_file_location("guangya_channel_ui_v1101_test", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)
GuangYaChannelUiV1101Mixin = module.GuangYaChannelUiV1101Mixin


def _contains_text(node, text):
    if isinstance(node, dict):
        if node.get("text") == text:
            return True
        return any(_contains_text(value, text) for value in node.values())
    if isinstance(node, list):
        return any(_contains_text(value, text) for value in node)
    return False


def _count_model(node, model):
    if isinstance(node, dict):
        count = 1 if isinstance(node.get("props"), dict) and node["props"].get("model") == model else 0
        return count + sum(_count_model(value, model) for value in node.values())
    if isinstance(node, list):
        return sum(_count_model(value, model) for value in node)
    return 0


class _Base:
    _channel_urls = "https://tgm.example/a\nhttps://tgm.example/b"

    def get_data(self, key):
        if key == "channel_index":
            return {
                "time": "2026-09-01 20:30:00",
                "errors": [],
                "items": [
                    {
                        "display_title": "测试剧集",
                        "tmdb_id": "12345",
                        "episode_hint": "S01E03",
                        "source_label": "热更频道",
                        "message_id": "100",
                        "candidate_types": ["guangya", "magnet", "ed2k"],
                        "share_url": "https://www.guangyapan.com/s/secret",
                        "external_sources": [{"uri": "magnet:?xt=urn:btih:SECRET"}],
                    }
                ],
            }
        return {}

    def _source_urls(self):
        return ["https://tgm.example/a", "https://tgm.example/b"]

    def _action(self, text, icon, path, **kwargs):
        return {"component": "VBtn", "text": text, "path": path}

    def _surface(self, title, subtitle, content, **kwargs):
        return {"component": "VCard", "title": title, "subtitle": subtitle, "content": content}

    def _section(self, title, subtitle, icon, rows):
        return {"component": "VCard", "text": title, "subtitle": subtitle, "content": rows}

    def _textarea(self, model, label, **kwargs):
        return {"component": "VCol", "content": [{"component": "VTextarea", "props": {"model": model, "label": label}}]}

    def _switch(self, model, label, **kwargs):
        return {"component": "VCol", "content": [{"component": "VSwitch", "props": {"model": model, "label": label}}]}

    def _field(self, model, label, **kwargs):
        return {"component": "VCol", "content": [{"component": "VTextField", "props": {"model": model, "label": label}}]}

    def get_page(self):
        return [
            {"text": "Hero"},
            {"text": "KPI"},
            {"text": "资源搜索与秒传"},
            {"text": "最近搜索结果"},
        ]

    def get_form(self):
        return [
            {
                "component": "VForm",
                "content": [
                    {"text": "统一资源决策"},
                    {"text": "接管与保存"},
                    {
                        "component": "VCard",
                        "content": [
                            {"text": "资源来源"},
                            {
                                "component": "VRow",
                                "content": [
                                    {"component": "VCol", "content": [{"props": {"model": "channel_urls"}}]},
                                    {"component": "VCol", "content": [{"props": {"model": "magnet_api_sources"}}]},
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "content": [{"props": {"model": "refresh_minutes"}}]},
                        ],
                    },
                ],
            }
        ], {"channel_urls": self._channel_urls}

    def get_api(self):
        return []


class _Plugin(GuangYaChannelUiV1101Mixin, _Base):
    pass


def test_channel_resources_are_first_class_console_section_and_redacted():
    plugin = _Plugin()
    page = plugin.get_page()
    assert page[3]["title"] == "频道资源"
    report = plugin.api_channel_resources()
    assert report["count"] == 1
    assert report["configured_sources"] == 2
    assert report["items"][0]["candidates"] == "光鸭 / Magnet / ED2K"
    public_text = str(report)
    assert "guangyapan.com" not in public_text
    assert "magnet:?" not in public_text
    assert any(item.get("path") == "/channels/resources" for item in plugin.get_api())


def test_config_has_dedicated_channel_section_without_duplicate_models():
    plugin = _Plugin()
    form, defaults = plugin.get_form()
    assert defaults["channel_urls"].startswith("https://tgm.example")
    assert _contains_text(form, "频道资源")
    assert _contains_text(form, "搜索补源")
    assert _count_model(form, "channel_urls") == 1
    assert _count_model(form, "refresh_minutes") == 1
    assert _count_model(form, "magnet_api_sources") == 1
