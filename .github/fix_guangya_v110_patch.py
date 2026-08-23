from pathlib import Path
p = Path('.github/guangya_transfer_v110_patch.py')
text = p.read_text(encoding='utf-8')
for name in ('new_page', 'new_try', 'new_inspect', 'new_restore'):
    text = text.replace(f'pattern.subn({name}, text, count=1)', f'pattern.subn(lambda _m: {name}, text, count=1)')
p.write_text(text, encoding='utf-8')
print('patched regex replacement callbacks')
