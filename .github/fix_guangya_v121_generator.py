from pathlib import Path

path = Path(__file__).with_name("guangya_transfer_v121_patch.py")
text = path.read_text(encoding="utf-8")

bad_regex = """        matched = re.search(r'''[\"'](?:value|title)[\"']\\s*:\\s*[\"']([^\"']+)[\"']''', raw)"""
good_regex = """        matched = re.search(r"[\\\"'](?:value|title)[\\\"']\\s*:\\s*[\\\"']([^\\\"']+)[\\\"']", raw)"""
if bad_regex in text:
    text = text.replace(bad_regex, good_regex, 1)

bad_fallback = """replace_once('            \"fallback_native\": self._fallback_native,\\n', '')
replace_once('            \"fallback_native\": self._fallback_native,\\n', '')"""
good_fallback = """text = text.replace('            \"fallback_native\": self._fallback_native,\\n', '')"""
if bad_fallback not in text:
    raise SystemExit("duplicate fallback removal block not found")
text = text.replace(bad_fallback, good_fallback, 1)

path.write_text(text, encoding="utf-8")
print("fixed GuangYa v1.2.1 patch generator quoting + duplicate fallback removal")
