from pathlib import Path
import json

ROOT = Path('.')
PLUGIN = ROOT / 'plugins.v3' / 'shukguangyadisk'
INIT = PLUGIN / '__init__.py'
PACKAGE = ROOT / 'package.v3.json'
PLUGIN_JSON = PLUGIN / 'plugin.json'
REMOTE = PLUGIN / 'dist' / 'assets' / 'remoteEntry.js'
PAGE310 = PLUGIN / 'dist' / 'assets' / '__federation_expose_AssistantPage-v310.js'
PAGE320 = PLUGIN / 'dist' / 'assets' / '__federation_expose_AssistantPage-v320.js'
TEST = ROOT / 'tests' / 'v3' / 'shukguangyadisk' / 'test_organizer_contract.py'

text = INIT.read_text(encoding='utf-8')
text = text.replace('from .organizer import GuangYaOrganizerMixin', 'from .organizer_v320 import GuangYaOrganizerMixin')
text = text.replace('plugin_version = "3.1.0"', 'plugin_version = "3.2.0"')
text = text.replace(
    'plugin_desc = "MoviePilot V3 光鸭云盘存储助手，新增按 MoviePilot 目录分类策略进行网盘内预览整理/移动/复制，并支持登录、浏览、上传、下载、WebDAV 和 Emby 直连。"',
    'plugin_desc = "MoviePilot V3 光鸭云盘存储助手：网盘内完整重新整理，复用 MP 媒体识别、目录分类和智能重命名模板，重建电影/电视剧/季目录并移动或复制到目标目录。"'
)
INIT.write_text(text, encoding='utf-8')

package = json.loads(PACKAGE.read_text(encoding='utf-8'))
entry = package['ShukGuangYaDisk']
entry['version'] = '3.2.0'
entry['description'] = '完整网盘重新整理：复用 MoviePilot 当前媒体识别、目录分类、类型/类别子目录和智能重命名模板，把光鸭云盘中的媒体重新命名并重建电影/电视剧/季目录结构后移动或复制到目标目录。'
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

local = json.loads(PLUGIN_JSON.read_text(encoding='utf-8'))
local['version'] = '3.2.0'
local['description'] = entry['description']
history = local.setdefault('history', {})
history['v3.2.0'] = '网盘整理升级为完整重新整理：递归扫描媒体文件，复用 MoviePilot TransHandler 预演最终路径，按当前 MP 智能重命名模板生成电影/电视剧/Season 目录和文件名；字幕等同名伴随文件同步改名；目标冲突按 MP 覆盖策略保护，移动模式完成后清理空源目录。'
PLUGIN_JSON.write_text(json.dumps(local, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

page = PAGE310.read_text(encoding='utf-8')
page = page.replace('GuangyaCloudAssistantV310', 'GuangyaCloudAssistantV320')
page = page.replace("'v3.1.0'", "'v3.2.0'")
page = page.replace(
    'MoviePilot 负责识别与目录分类策略，光鸭负责同盘移动/复制；执行前必须预览',
    'MoviePilot 负责识别、分类与智能重命名；光鸭按预览结果重建目录并同盘移动/复制'
)
page = page.replace(
    "h('div',{class:'gyo-chip'},[h('span','MP整理 / 覆盖'),h('b',`${selectedPolicy.value.transfer_type||'-'} / ${selectedPolicy.value.overwrite_mode||'never'}`)]),",
    "h('div',{class:'gyo-chip'},[h('span','MP整理 / 重命名 / 覆盖'),h('b',`${selectedPolicy.value.transfer_type||'-'} / ${selectedPolicy.value.renaming?'智能命名':'保留名'} / ${selectedPolicy.value.overwrite_mode||'never'}`)]),"
)
page = page.replace(
    "h('div',{class:'gyo-card-title'},'整理预览')",
    "h('div',{class:'gyo-card-title'},'完整重新整理预览')"
)
PAGE320.write_text(page, encoding='utf-8')

remote = REMOTE.read_text(encoding='utf-8')
remote = remote.replace('__federation_expose_AssistantPage-v310.js?v=3.1.0', '__federation_expose_AssistantPage-v320.js?v=3.2.0')
REMOTE.write_text(remote, encoding='utf-8')

old = TEST.read_text(encoding='utf-8')
old = old.replace('ORGANIZER = (PLUGIN / "organizer.py").read_text(encoding="utf-8")', 'ORGANIZER = (PLUGIN / "organizer_v320.py").read_text(encoding="utf-8")')
old = old.replace('PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v310.js").read_text(encoding="utf-8")', 'PAGE = (PLUGIN / "dist" / "assets" / "__federation_expose_AssistantPage-v320.js").read_text(encoding="utf-8")')
old = old.replace('def test_v310_version_and_federation_entry():', 'def test_v320_version_and_federation_entry():')
old = old.replace('"3.1.0"', '"3.2.0"')
old = old.replace('__federation_expose_AssistantPage-v310.js?v=3.1.0', '__federation_expose_AssistantPage-v320.js?v=3.2.0')
old = old.replace('    assert "保持光鸭原文件/目录名称" in ORGANIZER\n', '    assert "TransHandler" in ORGANIZER\n    assert "preview=True" in ORGANIZER\n    assert "target_name" in ORGANIZER\n    assert "伴随文件" in ORGANIZER\n')
if 'def test_v320_uses_moviepilot_native_rename_preview' not in old:
    old += '''\n\ndef test_v320_uses_moviepilot_native_rename_preview():\n    assert 'from app.modules.filemanager.transhandler import TransHandler' in ORGANIZER\n    assert 'transfer_media(' in ORGANIZER and 'preview=True' in ORGANIZER\n    assert '_collect_media_candidates' in ORGANIZER\n    assert '_preview_mp_target' in ORGANIZER\n    assert '_cleanup_empty_source_dirs' in ORGANIZER\n    assert '完整重新整理' in ORGANIZER\n    assert '重新命名' in PAGE or '智能重命名' in PAGE\n\n\ndef test_v320_plans_final_renamed_paths_and_companions():\n    assert 'target_name' in ORGANIZER\n    assert 'target_parent' in ORGANIZER\n    assert 'companions' in ORGANIZER\n    assert 'target_path' in ORGANIZER\n    assert '_preview_companion_target' in ORGANIZER\n    assert '目标路径完全相同' in ORGANIZER\n\n'''
TEST.write_text(old, encoding='utf-8')
print('patched GuangYa full organizer v3.2.0')
