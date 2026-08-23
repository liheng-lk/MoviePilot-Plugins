import ast
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

ROOT=Path(__file__).resolve().parents[3]
SRC=ROOT/'plugins.v3'/'guangyatransferassistant'/'__init__.py'
text=SRC.read_text(encoding='utf-8')
tree=ast.parse(text)

wanted={'_normalize_media_text','_canonical_share_url','_extract_channel_entries','_share_identity','_entry_matches_subscription'}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
for node in nodes:
    node.returns=None
    for arg in node.args.args:
        arg.annotation=None
mod=ast.Module(body=nodes,type_ignores=[])
ast.fix_missing_locations(mod)
ns={'html':html,'re':re,'parse_qs':parse_qs,'urlencode':urlencode,'urlsplit':urlsplit,'urlunsplit':urlunsplit,'Any':Any,'Dict':Dict,'List':List,'Optional':Optional,'SHARE_PATTERN':re.compile(r"https?://(?:www\.)?guangyapan\.com/(?:s|share)/[A-Za-z0-9_-]+(?:\?[^\s\"'<>]*)?",re.I),'CODE_PATTERN':re.compile(r"(?:提取码|密码|code)\s*[：:]?\s*([A-Za-z0-9]{2,16})",re.I)}
exec(compile(mod,str(SRC),'exec'),ns)

sample='''<div class="message">庆余年 第二季 2024 S02 最新更新 <a href="https://www.guangyapan.com/s/abc_DEF">光鸭</a> 提取码：9xY2</div>'''
items=ns['_extract_channel_entries'](sample,'https://tgm.li668.asia/regengguangya','影视热更')
assert len(items)==1
assert items[0]['share_id']=='abc_DEF'
assert 'code=9xY2' in items[0]['share_url']
assert ns['_entry_matches_subscription'](items[0],'庆余年 第二季',2024,2) is True
assert ns['_entry_matches_subscription'](items[0],'庆余年 第二季',2024,1) is False
assert ns['_entry_matches_subscription'](items[0],'完全不同的剧',2024,2) is False
assert ns['_share_identity']('https://www.guangyapan.com/s/abc_DEF?code=9xY2')=='abc_DEF|9xY2'

package=json.loads((ROOT/'package.v3.json').read_text(encoding='utf-8'))['GuangYaTransferAssistant']
local=json.loads((ROOT/'plugins.v3'/'guangyatransferassistant'/'plugin.json').read_text(encoding='utf-8'))
assert package['version']=='1.1.0' and local['version']=='1.1.0'
assert package['system_version']=='>=3.0.0'
assert 'plugin_version = "1.1.0"' in text
assert 'subscribe_search' in text and 'new_subscribe_search' in text
assert 'SubscribeChain().search' in text
assert 'ShukGuangYaDisk' in text and 'get_plugin_attr' in text
assert '/nd.bizuserres.s/v1/restore_share' in text
assert '/nd.bizuserres.s/v1/get_share_page_files_list' in text
assert 'tgm.li668.asia/regengguangya' in text
assert 'tgm.li668.asia/yunpanguangya' in text
assert 'VSelect' in text and 'selected_subscriptions' in text
assert 'VCombobox' in text and 'save_path' in text
assert 'fingerprint' in text
print('GuangYaTransferAssistant contract OK')

assert "stale_index" in text
assert "source_successes" in text
assert "if not valid:" in text


def test_transfer_notification_and_logging_contract():
    text = SRC.read_text(encoding="utf-8")
    assert 'from app.schemas import NotificationType' in text
    assert 'mtype=NotificationType.Plugin' in text
    assert '✅ 光鸭转存成功' in text
    assert '⚠️ 光鸭转存失败' in text
    assert '【光鸭转存助手】【转存】' in text
    assert '【光鸭转存助手】【回退】' in text
    assert '【光鸭转存助手】【通知】' in text
    assert '所有增量转存任务已确认完成' in text
    assert 'confirmed' in text
    assert 'task_ids' in text


def test_incremental_auto_transfer_contract():
    text = SRC.read_text(encoding="utf-8")
    assert 'auto_transfer_on_refresh' in text
    assert '_process_selected_subscriptions' in text
    assert 'transfer_inventory' in text
    assert '_plan_incremental_files' in text
    assert '_restore_items' in text
    assert '无新增文件' in text
    assert '热更只转存新增文件' in text or '同一分享热更不会重转旧文件' in text
    assert '频道资源（' in text
    assert '已记录去重资源' in text
    assert '增量转存成功' in text


def test_incremental_failure_is_not_misclassified_and_is_rate_limited():
    text = SRC.read_text(encoding="utf-8")
    assert 'attempted_new = False' in text
    assert 'if valid_match and not attempted_new:' in text
    assert 'failure_notices' in text
    assert '6 * 3600' in text
    assert '⚠️ 光鸭转存失败' in text


def test_legacy_fingerprint_migration_contract():
    text = SRC.read_text(encoding="utf-8")
    assert 'legacy_fingerprint_rows' in text
    assert 'legacy_fingerprint' in text
    assert 'old.get("fingerprint") in {fingerprint' in text
