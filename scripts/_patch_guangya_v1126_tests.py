from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for path in (ROOT / "tests").rglob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    original = text

    # Public release version expectations now point to v1.12.6.
    text = text.replace('"1.12.5"', '"1.12.6"')
    text = text.replace("'1.12.5'", "'1.12.6'")

    # Only entry-class build assertions move to r52; historical FINAL/PATCH mixin markers remain r51.
    lines = []
    for line in text.splitlines(keepends=True):
        if 'build_id = "20260904-r51"' in line and any(token in line for token in ("ENTRY", "entry", "self.entry")):
            line = line.replace('build_id = "20260904-r51"', 'build_id = "20260904-r52"')
        lines.append(line)
    text = "".join(lines)

    # v1.12.6 adds one new outer cooperative mixin immediately after PagePerf.
    old_pair = '"GuangYaPagePerfV1123Mixin",\n            "GuangYaDispatchPolicyFinalV1125Mixin",'
    new_pair = '"GuangYaPagePerfV1123Mixin",\n            "GuangYaFastRecallV1126Mixin",\n            "GuangYaDispatchPolicyFinalV1125Mixin",'
    if old_pair in text:
        text = text.replace(old_pair, new_pair)
        text = text.replace('mixins[:9]', 'mixins[:10]')

    if text != original:
        path.write_text(text, encoding="utf-8")

Path(__file__).unlink()
