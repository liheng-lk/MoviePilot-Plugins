from pathlib import Path
p = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = p.read_text(encoding='utf-8')
old = r'r"(?:^|[\s._])[-–—]\s*0*(\d{1,3})(?:v\d+)?(?=\s|[._\[(（]|$)"'
new = r'r"(?:^|[\s._])[-–—][\s._-]*0*(\d{1,3})(?:v\d+)?(?=\s|[._\[(（]|$)"'
if old not in text:
    raise SystemExit('dotted dash fallback anchor not found')
text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')
print('dotted dash episode fallback aligned')
