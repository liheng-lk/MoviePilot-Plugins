from pathlib import Path

root = Path(__file__).resolve().parents[1]
entry = root / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
text = entry.read_text(encoding="utf-8")

old = "from .airing_scheduler_v1120 import GuangYaAiringSchedulerV1120Mixin\n"
new = old + "from .airing_ui_v1120 import GuangYaAiringUiV1120Mixin\n"
if "from .airing_ui_v1120 import GuangYaAiringUiV1120Mixin" not in text:
    if old not in text:
        raise RuntimeError("cannot locate airing scheduler import")
    text = text.replace(old, new, 1)

old = "    GuangYaEpisodeFenceFinalV1124Mixin,\n    GuangYaReceiptCompletionV1124Mixin,\n    GuangYaGyingAutoLoginV1109Mixin,"
new = "    GuangYaEpisodeFenceFinalV1124Mixin,\n    GuangYaReceiptCompletionV1124Mixin,\n    GuangYaAiringUiV1120Mixin,\n    GuangYaGyingAutoLoginV1109Mixin,"
if "    GuangYaAiringUiV1120Mixin," not in text:
    if old not in text:
        raise RuntimeError("cannot locate receipt/fence MRO boundary")
    text = text.replace(old, new, 1)

entry.write_text(text, encoding="utf-8")
print("integrated airing UI below receipt completion")
