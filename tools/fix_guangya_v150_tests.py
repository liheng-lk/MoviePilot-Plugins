from pathlib import Path

path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    "    assert '模糊匹配' not in text\n",
    "    assert 'SequenceMatcher' not in text and 'rapidfuzz' not in text\n",
)
path.write_text(text, encoding='utf-8')
print('GuangYa v1.5.0 alias contract refined')
