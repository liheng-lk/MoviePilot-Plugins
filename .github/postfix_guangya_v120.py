from pathlib import Path
import re

path = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = path.read_text(encoding='utf-8')
pattern = re.compile(r'def _episode_numbers\(path: Any\) -> Tuple\[Optional\[int\], List\[int\]\]:.*?(?=\ndef _safe_relative_path)', re.S)
replacement = r'''def _episode_numbers(path: Any) -> Tuple[Optional[int], List[int]]:
    """从 S01E23、S01E23-E25、E23-E25、E23E24、中文第23-25集提取季和集。"""
    value = str(path or "")
    season = None
    episodes = set()

    # S01E23-E25 / S01E23E24 先处理，避免 E 前面是数字时被通用边界规则漏掉。
    season_block = re.search(r"(?i)S(?:eason)?\s*0*(\d{1,2})\s*E(?:P)?\s*0*(\d{1,3})(?:\s*[-~—至]\s*E?(?:P)?\s*0*(\d{1,3}))?", value)
    if season_block:
        season = int(season_block.group(1))
        start = int(season_block.group(2))
        end = int(season_block.group(3)) if season_block.group(3) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))
        # 同一个 season token 后续可能是 E23E24E25。
        suffix = value[season_block.start():]
        for ep in re.findall(r"(?i)E(?:P)?\s*0*(\d{1,3})", suffix):
            episodes.add(int(ep))
    else:
        season_match = re.search(r"(?i)(?:^|[^A-Za-z0-9])S(?:eason)?\s*0*(\d{1,2})(?=[^0-9]|$)", value)
        if season_match:
            season = int(season_match.group(1))

    # 独立 E23 / E23-E25。
    for matched in re.finditer(r"(?i)(?:^|[^A-Za-z0-9])E(?:P)?\s*0*(\d{1,3})(?:\s*[-~—至]\s*E?(?:P)?\s*0*(\d{1,3}))?", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))

    # 中文 第23-25集 / 第23至25集。
    for matched in re.finditer(r"第\s*(\d{1,3})(?:\s*[-~—至]\s*(\d{1,3}))?\s*集", value):
        start = int(matched.group(1))
        end = int(matched.group(2)) if matched.group(2) else start
        if end >= start and end - start <= 200:
            episodes.update(range(start, end + 1))

    return season, sorted(ep for ep in episodes if ep > 0)

'''
text, count = pattern.subn(lambda _m: replacement, text, count=1)
assert count == 1, 'episode parser block not found'
path.write_text(text, encoding='utf-8')
print('fixed episode range parser')
