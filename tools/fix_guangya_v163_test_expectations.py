from pathlib import Path
p = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = p.read_text(encoding='utf-8')
text = text.replace('data_schema_version = 5', 'data_schema_version = 6')
p.write_text(text, encoding='utf-8')
print('v1.6.3 schema test expectation aligned')
