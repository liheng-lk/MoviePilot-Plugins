from pathlib import Path

p = Path('plugins.v3/shukguangyadisk/organizer_v320.py')
text = p.read_text(encoding='utf-8')
old = '''    @staticmethod
    def _same_parent_same_stem_companions(video: Any, pool: List[Any]) -> List[Any]:
        video_stem = Path(str(getattr(video, "name", "") or "")).stem
        result: List[Any] = []
        for item in pool:
            if getattr(item, "type", "") != "file":
                continue
            name = str(getattr(item, "name", "") or "")
            if Path(name).stem == video_stem and Path(name).suffix.lower() in _EXTRA_COMPANION_EXTENSIONS:
                result.append(item)
        return result
'''
new = '''    @staticmethod
    def _same_parent_same_stem_companions(video: Any, pool: List[Any]) -> List[Any]:
        """匹配同名字幕/外置音轨；兼容 `.zh-CN`、`.CHS.forced` 等语言尾缀。"""
        video_stem = Path(str(getattr(video, "name", "") or "")).stem
        suffix_tags = {
            "zh", "cn", "tw", "hans", "hant", "chs", "cht", "sc", "tc",
            "en", "eng", "english", "ja", "jp", "jpn", "ko", "kor",
            "forced", "sdh", "default", "cc", "commentary",
            "简体", "繁体", "简中", "繁中", "中字", "中英", "双语",
        }
        result: List[Any] = []
        for item in pool:
            if getattr(item, "type", "") != "file":
                continue
            name = str(getattr(item, "name", "") or "")
            path = Path(name)
            if path.suffix.lower() not in _EXTRA_COMPANION_EXTENSIONS:
                continue
            companion_stem = path.stem
            if companion_stem == video_stem:
                result.append(item)
                continue
            if not companion_stem.startswith(video_stem):
                continue
            tail = companion_stem[len(video_stem):]
            if not tail or tail[0] not in ". _-[（(【":
                continue
            import re
            tags = [value.lower() for value in re.split(r"[\\s._\\-\\[\\]（）()【】]+", tail) if value]
            if tags and len(tags) <= 5 and all(tag in suffix_tags for tag in tags):
                result.append(item)
        return result
'''
if old not in text:
    raise SystemExit('companion matcher anchor not found')
text = text.replace(old, new, 1)

old2 = '''                ctarget = PurePosixPath(companion_target)
                companion_rows.append({
                    "source_path": self._organize_normalize_path(companion.path),
                    "source_fileid": str(companion.fileid or ""),
                    "source_name": str(companion.name or ""),
                    "target_path": companion_target,
                    "target_parent": self._organize_normalize_path(str(ctarget.parent)),
                    "target_name": ctarget.name,
                    "error": "",
                })

            status = "ready"
'''
new2 = '''                ctarget = PurePosixPath(companion_target)
                companion_existing = self._existing_exact_target(companion_target)
                companion_conflict = bool(
                    companion_existing
                    and str(getattr(companion_existing, "fileid", "") or "") != str(companion.fileid or "")
                    and self._organize_normalize_path(companion.path) != companion_target
                )
                companion_rows.append({
                    "source_path": self._organize_normalize_path(companion.path),
                    "source_fileid": str(companion.fileid or ""),
                    "source_name": str(companion.name or ""),
                    "target_path": companion_target,
                    "target_parent": self._organize_normalize_path(str(ctarget.parent)),
                    "target_name": ctarget.name,
                    "error": "",
                    "conflict": companion_conflict,
                })

            companion_errors = [row for row in companion_rows if row.get("error")]
            companion_conflicts = [row for row in companion_rows if row.get("conflict")]
            if companion_errors:
                decision = "conflict"
                reason = "伴随文件无法生成 MoviePilot 最终命名：" + ", ".join(
                    str(row.get("source_name") or "") for row in companion_errors[:3]
                )
            elif companion_conflicts and not allow_overwrite:
                decision = "conflict"
                reason = "伴随文件目标已存在，需要勾选允许按 MP 覆盖策略处理：" + ", ".join(
                    str(row.get("target_name") or "") for row in companion_conflicts[:3]
                )

            status = "ready"
'''
if old2 not in text:
    raise SystemExit('companion preflight anchor not found')
text = text.replace(old2, new2, 1)
p.write_text(text, encoding='utf-8')

# Add static regressions.
t = Path('tests/v3/shukguangyadisk/test_organizer_contract.py')
tests = t.read_text(encoding='utf-8')
if 'def test_v320_language_suffix_sidecars_and_preflight' not in tests:
    tests += '''\n\ndef test_v320_language_suffix_sidecars_and_preflight():\n    assert 'suffix_tags' in ORGANIZER\n    assert 'companion_stem.startswith(video_stem)' in ORGANIZER\n    assert 'companion_conflict' in ORGANIZER\n    assert 'companion_errors' in ORGANIZER\n    assert '伴随文件无法生成 MoviePilot 最终命名' in ORGANIZER\n    assert '伴随文件目标已存在' in ORGANIZER\n\n'''
t.write_text(tests, encoding='utf-8')
print('v3.2 sidecar matching/preflight hardened')
