from pathlib import Path

path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    "assert 'partial = (bool(errors) or remaining_due_to_cap > 0) and not completed_subscription' in flow",
    "assert 'partial = (bool(errors) or remaining_due_to_cap > 0 or pending_verification) and not completed_subscription' in flow",
)
path.write_text(text, encoding='utf-8')
print('pending verification partial-state test adapted')
