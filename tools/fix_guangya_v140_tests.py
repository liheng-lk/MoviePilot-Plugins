from pathlib import Path

path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    "assert 'if not force and self._entry_processed(entry):' in flow",
    "assert 'if not force and self._entry_processed(entry, subscribe):' in flow",
)
text = text.replace("'回退缓存'", "'故障回退'")
path.write_text(text, encoding='utf-8')
print('v1.4 legacy contract adapted')
