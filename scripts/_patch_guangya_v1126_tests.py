from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for path in (ROOT / "tests").rglob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    original = text

    # Public release version expectations now point to v1.12.6.
    text = text.replace('"1.12.5"', '"1.12.6"')
    text = text.replace("'1.12.5'", "'1.12.6'")

    # Only assertions that explicitly inspect the runtime ENTRY move to r52.
    # Historical v1.12.5 source-layer build markers must remain r51.
    lines = []
    for line in text.splitlines(keepends=True):
        if 'build_id = "20260904-r51"' in line and any(token in line for token in (" in ENTRY", " in entry", " in self.entry")):
            line = line.replace('build_id = "20260904-r51"', 'build_id = "20260904-r52"')
        lines.append(line)
    text = "".join(lines)

    # v1.12.6 adds one outer cooperative mixin immediately after PagePerf.
    old_pair = '"GuangYaPagePerfV1123Mixin",\n            "GuangYaDispatchPolicyFinalV1125Mixin",'
    new_pair = '"GuangYaPagePerfV1123Mixin",\n            "GuangYaFastRecallV1126Mixin",\n            "GuangYaDispatchPolicyFinalV1125Mixin",'
    if old_pair in text:
        text = text.replace(old_pair, new_pair)
        text = text.replace('mixins[:9]', 'mixins[:10]')
        text = text.replace('mixins[:10]', 'mixins[:11]')

    if text != original:
        path.write_text(text, encoding="utf-8")

# The primary release migrator intentionally operates broadly on current-version tests.
# Restore assertions that inspect historical v1.12.5 implementation files rather than ENTRY.
recall = ROOT / "tests/v3/guangyatransferassistant/test_gying_recall_guard_v1125.py"
text = recall.read_text(encoding="utf-8")
text = text.replace(
    'assert \'build_id = "20260904-r52"\' in guard_text',
    'assert \'build_id = "20260904-r51"\' in guard_text',
)
recall.write_text(text, encoding="utf-8")

hardening = ROOT / "tests/v3/guangyatransferassistant/test_gying_xunlei_recall_v1125.py"
text = hardening.read_text(encoding="utf-8")
text = text.replace(
    'assert \'build_id = "20260904-r52"\' in text',
    'assert \'build_id = "20260904-r51"\' in text',
)
text = text.replace(
    'assert \'build_id = "20260904-r51"\' in entry',
    'assert \'build_id = "20260904-r52"\' in entry',
)
hardening.write_text(text, encoding="utf-8")

# Airing UI authority list gains exactly one outer FastRecall layer.
airing_ui = ROOT / "tests/v3/guangyatransferassistant/test_airing_ui_v1120.py"
text = airing_ui.read_text(encoding="utf-8")
if '"GuangYaFastRecallV1126Mixin"' not in text:
    text = text.replace(
        '        "GuangYaPagePerfV1123Mixin",\n        "GuangYaDispatchPolicyFinalV1125Mixin",',
        '        "GuangYaPagePerfV1123Mixin",\n        "GuangYaFastRecallV1126Mixin",\n        "GuangYaDispatchPolicyFinalV1125Mixin",',
        1,
    )
text = text.replace('assert mixins[:10] == [', 'assert mixins[:11] == [', 1)
airing_ui.write_text(text, encoding="utf-8")

Path(__file__).unlink()
