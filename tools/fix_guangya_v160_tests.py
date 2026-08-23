from pathlib import Path

path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = path.read_text(encoding='utf-8')
text = text.replace("'data_schema_version = 4'", "'data_schema_version = 5'")
path.write_text(text, encoding='utf-8')
print('GuangYa v1.6.0 legacy schema assertion adapted')
