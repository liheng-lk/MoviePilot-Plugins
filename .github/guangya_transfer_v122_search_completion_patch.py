from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "plugins.v3" / "guangyatransferassistant" / "__init__.py"
TEST = ROOT / "tests" / "v3" / "guangyatransferassistant" / "test_plugin_contract.py"
PACKAGE = ROOT / "package.v3.json"
LOCAL = ROOT / "plugins.v3" / "guangyatransferassistant" / "plugin.json"

text = SRC.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one occurrence, got {count}: {old[:160]!r}")
    text = text.replace(old, new, 1)


replace_once('from app.chain.subscribe import SubscribeChain\n', 'from app.chain.subscribe import SubscribeChain, build_subscribe_meta\nfrom app.chain.media import MediaChain\n')
replace_once('    plugin_version = "1.2.1"', '    plugin_version = "1.2.2"')

old_select = '''                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VSelect", "props": {"model": "selected_subscriptions", "label": "选择仅使用光鸭转存的订阅", "items": subscriptions, "multiple": True, "chips": True, "clearable": True}}]},'''
new_select = '''                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VAutocomplete", "props": {"model": "selected_subscriptions", "label": "搜索并选择仅使用光鸭转存的订阅", "items": subscriptions, "multiple": True, "chips": True, "closable-chips": True, "clearable": True, "hide-selected": False, "hint": "可按剧名、年份、季、类型或订阅ID搜索", "persistent-hint": True, "prepend-inner-icon": "mdi-magnify"}}]},'''
replace_once(old_select, new_select)

old_option_block = '''    def _subscription_options(self) -> List[Dict[str, Any]]:
        options = []
        selected = set(self._selected_subscriptions)
        for sub in self._list_subscriptions(None):
            sid = int(getattr(sub, "id", 0) or 0)
            state = str(getattr(sub, "state", "") or "")
            if not sid or (state not in ("N", "R") and sid not in selected):
                continue
            season = getattr(sub, "season", None)
            suffix = f" S{int(season):02d}" if season not in (None, 0) else ""
            state_label = {"N": "新建", "R": "订阅中", "P": "待定", "S": "暂停"}.get(state, state or "-")
            options.append({"title": f"{sub.name} ({getattr(sub, 'year', '') or '-'}){suffix} · {state_label} · #{sid}", "value": sid})
        return options
'''
new_option_block = '''    @staticmethod
    def _subscription_episode_progress(subscribe: Any) -> Tuple[int, int, int]:
        """按 MoviePilot note 与目标集范围计算已完成、目标和剩余集数。"""
        media_type = str(getattr(subscribe, "type", "") or "").lower()
        if "tv" not in media_type and "电视剧" not in str(getattr(subscribe, "type", "") or "") and getattr(subscribe, "season", None) in (None, 0):
            return 0, 0, 0
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
        except (TypeError, ValueError):
            return 0, 0, 0
        if total < start:
            return 0, 0, 0
        target = set(range(start, total + 1))
        done = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                episode = int(value)
            except (TypeError, ValueError):
                continue
            if episode in target:
                done.add(episode)
        return len(done), len(target), len(target - done)

    def _subscription_options(self) -> List[Dict[str, Any]]:
        options = []
        selected = set(self._selected_subscriptions)
        for sub in self._list_subscriptions(None):
            sid = int(getattr(sub, "id", 0) or 0)
            state = str(getattr(sub, "state", "") or "")
            if not sid or (state not in ("N", "R") and sid not in selected):
                continue
            season = getattr(sub, "season", None)
            suffix = f" S{int(season):02d}" if season not in (None, 0) else ""
            state_label = {"N": "新建", "R": "订阅中", "P": "待定", "S": "暂停"}.get(state, state or "-")
            media_type = str(getattr(sub, "type", "") or "").strip() or "媒体"
            done, total, lack = self._subscription_episode_progress(sub)
            progress = f" · 已完成 {done}/{total} · 剩余 {lack}" if total else ""
            options.append({"title": f"{sub.name} ({getattr(sub, 'year', '') or '-'}){suffix} · {media_type} · {state_label}{progress} · #{sid}", "value": sid})
        return options
'''
replace_once(old_option_block, new_option_block)

old_row_text = '''            state_text = (f"{recent[0].get('time') or '-'} · {recent[0].get('message') or '-'}" if recent else "等待频道匹配")
            state = str(getattr(sub, "state", "") or "-")
            rows.append({'''
new_row_text = '''            state_text = (f"{recent[0].get('time') or '-'} · {recent[0].get('message') or '-'}" if recent else "等待频道匹配")
            state = str(getattr(sub, "state", "") or "-")
            done, total, lack = self._subscription_episode_progress(sub)
            progress_text = f" · 已完成 {done}/{total} 集 · 剩余 {lack} 集" if total else ""
            rows.append({'''
replace_once(old_row_text, new_row_text)
replace_once('''                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state} · 去重资源 {asset_count} 个 · {state_text}"},''', '''                    {"component": "VCardText", "text": f"订阅ID {sid} · 状态 {state}{progress_text} · 去重资源 {asset_count} 个 · {state_text}"},''')

old_sync = '''    def _sync_progress(self, subscribe: Any, completed: List[Dict[str, Any]]) -> None:
        """确认转存成功后把剧集写入 MoviePilot note，避免后续原生搜索重复下载。"""
        if not self._sync_subscription_progress or bool(getattr(subscribe, "best_version", 0)):
            return
        mtype = str(getattr(subscribe, "type", "") or "").lower()
        if "tv" not in mtype and "电视剧" not in str(getattr(subscribe, "type", "") or "") and getattr(subscribe, "season", None) in (None, 0):
            return
        episodes = set()
        wanted_season = getattr(subscribe, "season", None)
        for item in completed:
            path = item.get("effective_path") or item.get("relative_path") or item.get("name") or ""
            if not _is_video(path):
                continue
            file_season, values = _episode_numbers(path)
            if wanted_season not in (None, 0) and file_season not in (None, int(wanted_season)):
                continue
            episodes.update(values)
        if not episodes:
            return
        current = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                current.add(int(value))
            except (TypeError, ValueError):
                continue
        merged = current | episodes
        if merged == current:
            return
        payload: Dict[str, Any] = {"note": sorted(merged)}
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
            if total >= start:
                payload["lack_episode"] = len(set(range(start, total + 1)) - merged)
        except (TypeError, ValueError):
            pass
        try:
            SubscribeOper().update(int(getattr(subscribe, "id", 0) or 0), payload)
            setattr(subscribe, "note", sorted(merged))
            if "lack_episode" in payload:
                setattr(subscribe, "lack_episode", payload["lack_episode"])
            logger.info("【光鸭转存助手】【进度】#%s %s 已同步剧集 %s 到 MoviePilot note", getattr(subscribe, "id", 0), getattr(subscribe, "name", ""), ",".join(str(v) for v in sorted(episodes)))
        except Exception as err:
            logger.warning("【光鸭转存助手】【进度】同步 MoviePilot 订阅进度失败：%s", err)
'''
new_sync = '''    def _sync_progress(self, subscribe: Any, completed: List[Dict[str, Any]]) -> None:
        """确认转存成功后同步 MoviePilot note 和 lack_episode。"""
        if not self._sync_subscription_progress or bool(getattr(subscribe, "best_version", 0)):
            return
        mtype = str(getattr(subscribe, "type", "") or "").lower()
        if "tv" not in mtype and "电视剧" not in str(getattr(subscribe, "type", "") or "") and getattr(subscribe, "season", None) in (None, 0):
            return
        episodes = set()
        wanted_season = getattr(subscribe, "season", None)
        for item in completed:
            path = item.get("effective_path") or item.get("relative_path") or item.get("name") or ""
            if not _is_video(path):
                continue
            file_season, values = _episode_numbers(path)
            if wanted_season not in (None, 0) and file_season not in (None, int(wanted_season)):
                continue
            episodes.update(values)
        if not episodes:
            return
        current = set()
        for value in (getattr(subscribe, "note", None) or []):
            try:
                current.add(int(value))
            except (TypeError, ValueError):
                continue
        merged = current | episodes
        payload: Dict[str, Any] = {"note": sorted(merged)}
        try:
            start = max(1, int(getattr(subscribe, "start_episode", 0) or 1))
            total = int(getattr(subscribe, "total_episode", 0) or 0)
            if total >= start:
                target = set(range(start, total + 1))
                payload["lack_episode"] = len(target - merged)
        except (TypeError, ValueError):
            pass
        try:
            SubscribeOper().update(int(getattr(subscribe, "id", 0) or 0), payload)
            setattr(subscribe, "note", sorted(merged))
            if "lack_episode" in payload:
                setattr(subscribe, "lack_episode", payload["lack_episode"])
            done, total, lack = self._subscription_episode_progress(subscribe)
            logger.info(
                "【光鸭转存助手】【进度】#%s %s 本次确认剧集 %s；已完成 %s/%s，剩余 %s",
                getattr(subscribe, "id", 0), getattr(subscribe, "name", ""),
                ",".join(str(v) for v in sorted(episodes)), done, total, lack,
            )
        except Exception as err:
            logger.warning("【光鸭转存助手】【进度】同步 MoviePilot 订阅进度失败：%s", err)

    def _finish_subscription_if_complete(self, subscribe: Any) -> bool:
        """目标集全部完成时调用 MoviePilot 官方完成流程并清理固定分流 ID。"""
        if not self._sync_subscription_progress or bool(getattr(subscribe, "best_version", 0)):
            return False
        sid = int(getattr(subscribe, "id", 0) or 0)
        if not sid:
            return False
        done, total, lack = self._subscription_episode_progress(subscribe)
        if not total or lack > 0:
            if total:
                try:
                    if int(getattr(subscribe, "lack_episode", lack) or 0) != lack:
                        SubscribeOper().update(sid, {"lack_episode": lack})
                        setattr(subscribe, "lack_episode", lack)
                except Exception as err:
                    logger.warning("【光鸭转存助手】【进度】更新剩余集数失败：%s", err)
            return False
        latest = self._find_subscription(sid)
        if not latest:
            self._remove_selected_subscription(sid)
            return True
        try:
            meta = build_subscribe_meta(latest)
            mediainfo = MediaChain().recognize_media(
                meta=meta,
                mtype=meta.type,
                media_source=getattr(latest, "media_source", None),
                media_id=getattr(latest, "media_id", None),
                episode_group=getattr(latest, "episode_group", None),
                cache=False,
            )
            if not mediainfo:
                logger.warning("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，但媒体识别失败，暂不移除订阅", sid, getattr(latest, "name", ""), done, total)
                return False
            SubscribeChain().finish_subscribe_or_not(
                subscribe=latest,
                meta=meta,
                mediainfo=mediainfo,
                lefts={},
                force=True,
            )
            if self._find_subscription(sid):
                logger.warning("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，但 MoviePilot 完成流程后订阅仍存在", sid, getattr(latest, "name", ""), done, total)
                return False
            self._remove_selected_subscription(sid)
            logger.info("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，剩余 0；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""), done, total)
            return True
        except Exception as err:
            logger.exception("【光鸭转存助手】【完成】#%s %s 执行 MoviePilot 官方完成流程失败", sid, getattr(subscribe, "name", ""))
            return False

    def _remove_selected_subscription(self, sid: int) -> None:
        """订阅完成后同步移除插件固定转存名单中的订阅 ID。"""
        selected = [value for value in self._selected_subscriptions if int(value) != int(sid)]
        if selected == self._selected_subscriptions:
            return
        self._selected_subscriptions = selected
        self._save_config()
'''
replace_once(old_sync, new_sync)

old_guard = '''        allowed, guard_reason = self._subscription_static_guard(subscribe)
        if not allowed:
            logger.info("【光鸭转存助手】【规则】#%s %s 不接管：%s", sid, getattr(subscribe, "name", ""), guard_reason)
            return {"success": False, "handled": True, "message": guard_reason}
        self.refresh_channels(force=False)
'''
new_guard = '''        allowed, guard_reason = self._subscription_static_guard(subscribe)
        if not allowed:
            logger.info("【光鸭转存助手】【规则】#%s %s 不接管：%s", sid, getattr(subscribe, "name", ""), guard_reason)
            return {"success": False, "handled": True, "message": guard_reason}
        # 兼容旧版本已经转存完、note/lack_episode 已更新但尚未触发订阅完成的记录。
        if self._finish_subscription_if_complete(subscribe):
            return {"success": True, "handled": True, "completed": True, "message": "目标剧集已全部完成，订阅已移入历史"}
        self.refresh_channels(force=False)
'''
replace_once(old_guard, new_guard)

old_unique = '''        if unique_paths:
            partial = bool(errors)
            logger.info("【光鸭转存助手】【转存】#%s %s %s：新增 %s 个文件，累计去重 %s 个，剩余待下轮 %s，目标=%s", sid, getattr(subscribe, "name", ""), "部分完成" if partial else "增量完成", len(unique_paths), len(assets), remaining_due_to_cap, target_path)
'''
new_unique = '''        if unique_paths:
            completed_subscription = self._finish_subscription_if_complete(subscribe)
            partial = bool(errors) and not completed_subscription
            logger.info("【光鸭转存助手】【转存】#%s %s %s：新增 %s 个文件，累计去重 %s 个，剩余待下轮 %s，目标=%s", sid, getattr(subscribe, "name", ""), "订阅完成" if completed_subscription else ("部分完成" if partial else "增量完成"), len(unique_paths), len(assets), remaining_due_to_cap, target_path)
'''
replace_once(old_unique, new_unique)

old_lines = '''                    f"本次新增：{len(unique_paths)} 个文件",
                    f"累计去重：{len(assets)} 个文件",
                    f"来源：{'、'.join(sorted(sources))}",'''
new_lines = '''                    f"本次新增：{len(unique_paths)} 个文件",
                    f"累计去重：{len(assets)} 个文件",
                    (lambda p: f"订阅进度：{p[0]}/{p[1]}，剩余 {p[2]} 集" if p[1] else "订阅进度：非剧集订阅")(self._subscription_episode_progress(subscribe)),
                    f"来源：{'、'.join(sorted(sources))}",'''
replace_once(old_lines, new_lines)

old_title = '''                self.post_message(mtype=NotificationType.Plugin, title="⚠️ 光鸭部分转存" if partial else "✅ 光鸭转存成功", text="\\n".join(lines))'''
new_title = '''                self.post_message(mtype=NotificationType.Plugin, title="✅ 光鸭订阅完成" if completed_subscription else ("⚠️ 光鸭部分转存" if partial else "✅ 光鸭转存成功"), text="\\n".join(lines))'''
replace_once(old_title, new_title)

old_synced = '''        if valid_route_match and (synchronized_match or not attempted_new):
            logger.info("【光鸭转存助手】【去重】#%s %s 所有有效匹配均无新增，保持光鸭优先，不触发重复下载", sid, getattr(subscribe, "name", ""))
            return {"success": True, "handled": True, "already": True, "message": "已同步，无新增资源"}
'''
new_synced = '''        if valid_route_match and (synchronized_match or not attempted_new):
            if self._finish_subscription_if_complete(subscribe):
                return {"success": True, "handled": True, "completed": True, "message": "目标剧集已全部完成，订阅已移入历史"}
            done, total, lack = self._subscription_episode_progress(subscribe)
            logger.info("【光鸭转存助手】【去重】#%s %s 所有有效匹配均无新增；订阅进度 %s/%s，剩余 %s；固定转存路线不触发重复下载", sid, getattr(subscribe, "name", ""), done, total, lack)
            return {"success": True, "handled": True, "already": True, "message": f"已同步，无新增资源；进度 {done}/{total}，剩余 {lack}" if total else "已同步，无新增资源"}
'''
replace_once(old_synced, new_synced)

SRC.write_text(text, encoding="utf-8")

package = json.loads(PACKAGE.read_text(encoding="utf-8"))
row = package["GuangYaTransferAssistant"]
row["version"] = "1.2.2"
row["description"] = "光鸭订阅固定分流：订阅选择支持快速搜索；转存集数实时同步 MoviePilot，剩余为0时走官方完成流程自动移除活动订阅。"
history = row.setdefault("history", {})
row["history"] = {
    "v1.2.2": "订阅选择器升级为可搜索多选，支持按剧名、年份、季、媒体类型和订阅ID快速定位；转存确认后同步 note/lack_episode，显示已完成/总集/剩余集，目标集全部完成时调用 MoviePilot 官方订阅完成流程移入历史并清理固定转存名单；兼容修复旧版本已完成但未移除的订阅。",
    **history,
}
PACKAGE.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

local = json.loads(LOCAL.read_text(encoding="utf-8"))
local["version"] = "1.2.2"
local["description"] = "固定转存订阅，支持订阅快速搜索、剧集进度同步及完成后自动移入订阅历史。"
LOCAL.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
test = test.replace('assert package["version"] == "1.2.1" and local["version"] == "1.2.1"', 'assert package["version"] == "1.2.2" and local["version"] == "1.2.2"')
test = test.replace("assert 'plugin_version = \"1.2.1\"' in text", "assert 'plugin_version = \"1.2.2\"' in text")
append = '''\n\ndef test_subscription_selector_is_searchable_and_progress_aware():\n    assert '\"component\": \"VAutocomplete\"' in text\n    assert '搜索并选择仅使用光鸭转存的订阅' in text\n    assert '可按剧名、年份、季、类型或订阅ID搜索' in text\n    assert 'prepend-inner-icon' in text and 'mdi-magnify' in text\n    assert '_subscription_episode_progress' in text\n    assert '已完成 {done}/{total}' in text\n    assert '剩余 {lack}' in text\n\n\ndef test_completed_guangya_subscription_uses_moviepilot_completion_flow():\n    assert 'build_subscribe_meta' in text\n    assert 'MediaChain().recognize_media' in text\n    assert 'SubscribeChain().finish_subscribe_or_not' in text\n    assert 'force=True' in text\n    assert '_finish_subscription_if_complete' in text\n    assert '_remove_selected_subscription' in text\n    assert '已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除' in text\n    assert '目标剧集已全部完成，订阅已移入历史' in text\n'''
if 'def test_subscription_selector_is_searchable_and_progress_aware()' not in test:
    test += append
TEST.write_text(test, encoding="utf-8")

print("patched GuangYa Transfer Assistant v1.2.2 search + completion lifecycle")
