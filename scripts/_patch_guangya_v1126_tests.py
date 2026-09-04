import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Migrate public release-version expectations and final runtime ENTRY build assertions.
for path in (ROOT / "tests").rglob("test_*.py"):
    text = path.read_text(encoding="utf-8")
    original = text
    text = text.replace('"1.12.5"', '"1.12.6"')
    text = text.replace("'1.12.5'", "'1.12.6'")
    lines = []
    for line in text.splitlines(keepends=True):
        if 'build_id = "20260904-r51"' in line and any(
            token in line for token in (" in ENTRY", " in entry_text", " in entry", ", self.entry")
        ):
            line = line.replace('build_id = "20260904-r51"', 'build_id = "20260904-r52"')
        lines.append(line)
    text = "".join(lines)
    if text != original:
        path.write_text(text, encoding="utf-8")


def add_fast_recall(path: Path, old_slice: str, new_slice: str) -> None:
    text = path.read_text(encoding="utf-8")
    if '"GuangYaFastRecallV1126Mixin"' not in text:
        text, count = re.subn(
            r'(?m)^(\s*)"GuangYaPagePerfV1123Mixin",\n\1"GuangYaDispatchPolicyFinalV1125Mixin",',
            lambda match: (
                f'{match.group(1)}"GuangYaPagePerfV1123Mixin",\n'
                f'{match.group(1)}"GuangYaFastRecallV1126Mixin",\n'
                f'{match.group(1)}"GuangYaDispatchPolicyFinalV1125Mixin",'
            ),
            text,
            count=1,
        )
        assert count == 1, path
    text = text.replace(old_slice, new_slice, 1)
    path.write_text(text, encoding="utf-8")


# Root MRO contracts previously covered 9 layers; v1.12.6 adds exactly one outer layer.
add_fast_recall(
    ROOT / "tests/test_guangya_receipt_completion_v1124.py",
    "mixins[:9]",
    "mixins[:10]",
)
add_fast_recall(
    ROOT / "tests/test_guangya_release_v1110.py",
    "mixins[:9]",
    "mixins[:10]",
)

# Airing UI contract previously covered 10 layers; now it covers 11.
add_fast_recall(
    ROOT / "tests/v3/guangyatransferassistant/test_airing_ui_v1120.py",
    "mixins[:10]",
    "mixins[:11]",
)

# Historical v1.12.5 implementation files themselves remain r51; only ENTRY is r52.
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

Path(__file__).unlink()
