from pathlib import Path

src = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = src.read_text(encoding='utf-8')
text = text.replace(
    '        fingerprint_rows: List[str] = []\n        files: List[Dict[str, Any]] = []',
    '        fingerprint_rows: List[str] = []\n        legacy_fingerprint_rows: List[str] = []\n        files: List[Dict[str, Any]] = []',
    1,
)
text = text.replace(
    '                    fingerprint_rows.append(f"{item[\'id\']}|{rel}|{item[\'size\']}|{int(item[\'is_dir\'])}")\n                    if item["is_dir"]:',
    '                    fingerprint_rows.append(f"{item[\'id\']}|{rel}|{item[\'size\']}|{int(item[\'is_dir\'])}")\n                    legacy_fingerprint_rows.append(f"{item[\'id\']}|{item[\'name\']}|{item[\'size\']}|{int(item[\'is_dir\'])}")\n                    if item["is_dir"]:',
    1,
)
text = text.replace(
    '        fingerprint = hashlib.sha256("\\n".join(sorted(fingerprint_rows)).encode("utf-8")).hexdigest()\n        result = {',
    '        fingerprint = hashlib.sha256("\\n".join(sorted(fingerprint_rows)).encode("utf-8")).hexdigest()\n        legacy_fingerprint = hashlib.sha256("\\n".join(sorted(legacy_fingerprint_rows)).encode("utf-8")).hexdigest()\n        result = {',
    1,
)
text = text.replace(
    '            "fingerprint": fingerprint, "file_count": count,',
    '            "fingerprint": fingerprint, "legacy_fingerprint": legacy_fingerprint, "file_count": count,',
    1,
)
old = '            if not assets and old.get("success") and fingerprint and old.get("fingerprint") == fingerprint:'
new = '            if not assets and old.get("success") and old.get("fingerprint") in {fingerprint, str(probe.get("legacy_fingerprint") or "")}:'
assert old in text
text = text.replace(old, new, 1)
src.write_text(text, encoding='utf-8')

test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
test = test_path.read_text(encoding='utf-8')
if 'test_legacy_fingerprint_migration_contract' not in test:
    test += '''\n\ndef test_legacy_fingerprint_migration_contract():\n    text = SRC.read_text(encoding="utf-8")\n    assert 'legacy_fingerprint_rows' in text\n    assert 'legacy_fingerprint' in text\n    assert 'old.get("fingerprint") in {fingerprint' in text\n'''
test_path.write_text(test, encoding='utf-8')
