from pathlib import Path

path = Path(__file__).with_name("guangya_transfer_v121_patch.py")
text = path.read_text(encoding="utf-8")
bad = """        matched = re.search(r'''[\"'](?:value|title)[\"']\\s*:\\s*[\"']([^\"']+)[\"']''', raw)"""
good = """        matched = re.search(r"[\\\"'](?:value|title)[\\\"']\\s*:\\s*[\\\"']([^\\\"']+)[\\\"']", raw)"""
if bad not in text:
    raise SystemExit("target regex line not found")
text = text.replace(bad, good, 1)
path.write_text(text, encoding="utf-8")
print("fixed GuangYa v1.2.1 patch generator quoting")
