from pathlib import Path

path = Path('.github/guangya_transfer_v120_patch.py')
text = path.read_text(encoding='utf-8')
start = "test = r'''import ast\n"
end = "\n'''\nTEST.write_text(test, encoding=\"utf-8\")"
assert start in text, 'test template start not found'
assert end in text, 'test template end not found'
text = text.replace(start, 'test = r"""import ast\n', 1)
text = text.replace(end, '\n"""\nTEST.write_text(test, encoding="utf-8")', 1)
path.write_text(text, encoding='utf-8')
print('fixed v1.2.0 generator quoting')
