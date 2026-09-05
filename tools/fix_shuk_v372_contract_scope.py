from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "tests" / "v3" / "shukguangyadisk" / "test_loss_guard_v349.py"
text = path.read_text(encoding="utf-8")
old = '''    assert CONFLICT.index('preview_kwargs["preview"] = True') < CONFLICT.index("_loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))")\n'''
new = '''    execute = CONFLICT[CONFLICT.index("def _execute_conflict_aware"):]
    assert execute.index('preview_kwargs["preview"] = True') < execute.index("_loss_guard._normalize_result(transfer_chain.do_transfer(**kwargs))")\n'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"expected one preview ordering assertion, got {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("v3.7.2 preview ordering contract scoped to explicit execution entry")
