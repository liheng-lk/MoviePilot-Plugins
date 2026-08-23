from pathlib import Path
p = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = p.read_text(encoding='utf-8')
text = text.replace("force_pos = block.index('_try_transfer_subscription(subscribe, force=True)')", "force_pos = block.index('_try_transfer_subscription(subscribe, force=True, refresh_channel=False)')")
p.write_text(text, encoding='utf-8')
print('v1.6.4 test expectation aligned')
