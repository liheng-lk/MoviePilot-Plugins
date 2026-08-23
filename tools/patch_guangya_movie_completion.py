from pathlib import Path

src = Path('plugins.v3/guangyatransferassistant/__init__.py')
text = src.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'{label} anchor not found')
    text = text.replace(old, new, 1)


# 媒体库同步后，不依赖频道是否匹配也先尝试完成订阅：
# - TV：媒体库已补齐全部目标集时可完成，同时仍受连载保护；
# - Movie：媒体库已存在或此前已确认转存视频时可完成。
old_pre_match = '''        self.refresh_channels(force=False)\n        # 每轮先以媒体库为事实源同步当前目标范围，频道没有新链接时也能去掉已入库重复集。\n        self._sync_media_library_progress(subscribe)\n        entries = list((self.get_data("channel_index") or {}).get("items") or [])\n        matched_pairs = []\n'''
new_pre_match = '''        self.refresh_channels(force=False)\n        # 每轮先以媒体库为事实源同步当前目标范围，频道没有新链接时也能去掉已入库重复集。\n        self._sync_media_library_progress(subscribe)\n        entries = list((self.get_data("channel_index") or {}).get("items") or [])\n        pre_channel_state = self._channel_state_for_subscription(subscribe, entries)\n        if self._finish_subscription_if_complete(subscribe, channel_state=pre_channel_state):\n            media_kind = "电影" if self._is_movie_subscription(subscribe) else "剧集"\n            return {"success": True, "handled": True, "completed": True, "message": f"{media_kind}目标已完成，订阅已移入历史"}\n        matched_pairs = []\n'''
replace_once(old_pre_match, new_pre_match, 'pre-match completion')

old_finish = '''    def _finish_subscription_if_complete(self, subscribe: Any, channel_state: Optional[Dict[str, Any]] = None) -> bool:\n        """目标集全部完成且通过连载保护后，调用 MoviePilot 官方完成流程。"""\n        if not self._sync_subscription_progress or bool(getattr(subscribe, "best_version", 0)):\n            return False\n        sid = int(getattr(subscribe, "id", 0) or 0)\n        if not sid:\n            return False\n        done, total, lack = self._subscription_episode_progress(subscribe)\n        if not total or lack > 0:\n            self._clear_completion_guard(sid)\n            if total:\n                try:\n                    if int(getattr(subscribe, "lack_episode", lack) or 0) != lack:\n                        SubscribeOper().update(sid, {"lack_episode": lack})\n                        setattr(subscribe, "lack_episode", lack)\n                except Exception as err:\n                    logger.warning("【光鸭转存助手】【进度】更新剩余集数失败：%s", err)\n            return False\n        if not self._completion_guard_allows(subscribe, channel_state=channel_state):\n            return False\n        latest = self._find_subscription(sid)\n        if not latest:\n            self._remove_selected_subscription(sid)\n            return True\n        try:\n            meta = build_subscribe_meta(latest)\n            mediainfo = MediaChain().recognize_media(\n                meta=meta,\n                mtype=meta.type,\n                media_source=getattr(latest, "media_source", None),\n                media_id=getattr(latest, "media_id", None),\n                episode_group=getattr(latest, "episode_group", None),\n                cache=False,\n            )\n            if not mediainfo:\n                logger.warning("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，但媒体识别失败，暂不移除订阅", sid, getattr(latest, "name", ""), done, total)\n                return False\n            SubscribeChain().finish_subscribe_or_not(\n                subscribe=latest,\n                meta=meta,\n                mediainfo=mediainfo,\n                lefts={},\n                force=True,\n            )\n            if self._find_subscription(sid):\n                logger.warning("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，但 MoviePilot 完成流程后订阅仍存在", sid, getattr(latest, "name", ""), done, total)\n                return False\n            self._clear_completion_guard(sid)\n            self._remove_selected_subscription(sid)\n            logger.info("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，剩余 0；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""), done, total)\n            return True\n        except Exception:\n            logger.exception("【光鸭转存助手】【完成】#%s %s 执行 MoviePilot 官方完成流程失败", sid, getattr(subscribe, "name", ""))\n            return False\n'''
new_finish = '''    @staticmethod\n    def _is_movie_subscription(subscribe: Any) -> bool:\n        raw_type = str(getattr(subscribe, "type", "") or "")\n        mtype = raw_type.lower()\n        return "movie" in mtype or "电影" in raw_type\n\n    def _movie_transfer_confirmed(self, subscribe: Any) -> bool:\n        """电影只在媒体库已存在或已确认至少一个视频文件成功转存后允许完成。"""\n        sid = int(getattr(subscribe, "id", 0) or 0)\n        if not sid:\n            return False\n        inventory = self.get_data("transfer_inventory") or {}\n        assets = ((inventory.get(str(sid)) or {}).get("assets") or {})\n        for row in assets.values():\n            if not isinstance(row, dict):\n                continue\n            path = str(row.get("path") or "")\n            if path and _is_video(path):\n                return True\n        try:\n            meta = build_subscribe_meta(subscribe)\n            mediainfo = MediaChain().recognize_media(\n                meta=meta,\n                mtype=meta.type,\n                media_source=getattr(subscribe, "media_source", None),\n                media_id=getattr(subscribe, "media_id", None),\n                episode_group=getattr(subscribe, "episode_group", None),\n                cache=False,\n            )\n            if not mediainfo:\n                return False\n            exists, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)\n            if exists:\n                logger.info("【光鸭转存助手】【媒体库同步】#%s %s 电影已存在于媒体库，允许完成订阅", sid, getattr(subscribe, "name", ""))\n                return True\n        except Exception as err:\n            logger.warning("【光鸭转存助手】【媒体库同步】#%s %s 检查电影媒体库状态失败：%s", sid, getattr(subscribe, "name", ""), err)\n        return False\n\n    def _finish_subscription_if_complete(self, subscribe: Any, channel_state: Optional[Dict[str, Any]] = None) -> bool:\n        """电影按确认转存/媒体库存在完成；剧集按目标集进度并通过连载保护后完成。"""\n        if bool(getattr(subscribe, "best_version", 0)):\n            return False\n        sid = int(getattr(subscribe, "id", 0) or 0)\n        if not sid:\n            return False\n        is_movie = self._is_movie_subscription(subscribe)\n        done = total = lack = 0\n        if is_movie:\n            if not self._movie_transfer_confirmed(subscribe):\n                return False\n            self._clear_completion_guard(sid)\n        else:\n            if not self._sync_subscription_progress:\n                return False\n            done, total, lack = self._subscription_episode_progress(subscribe)\n            if not total or lack > 0:\n                self._clear_completion_guard(sid)\n                if total:\n                    try:\n                        if int(getattr(subscribe, "lack_episode", lack) or 0) != lack:\n                            SubscribeOper().update(sid, {"lack_episode": lack})\n                            setattr(subscribe, "lack_episode", lack)\n                    except Exception as err:\n                        logger.warning("【光鸭转存助手】【进度】更新剩余集数失败：%s", err)\n                return False\n            if not self._completion_guard_allows(subscribe, channel_state=channel_state):\n                return False\n        latest = self._find_subscription(sid)\n        if not latest:\n            self._remove_selected_subscription(sid)\n            return True\n        try:\n            meta = build_subscribe_meta(latest)\n            mediainfo = MediaChain().recognize_media(\n                meta=meta,\n                mtype=meta.type,\n                media_source=getattr(latest, "media_source", None),\n                media_id=getattr(latest, "media_id", None),\n                episode_group=getattr(latest, "episode_group", None),\n                cache=False,\n            )\n            if not mediainfo:\n                progress = "电影已确认转存" if is_movie else f"已完成 {done}/{total}"\n                logger.warning("【光鸭转存助手】【完成】#%s %s %s，但媒体识别失败，暂不移除订阅", sid, getattr(latest, "name", ""), progress)\n                return False\n            SubscribeChain().finish_subscribe_or_not(\n                subscribe=latest,\n                meta=meta,\n                mediainfo=mediainfo,\n                lefts={},\n                force=True,\n            )\n            if self._find_subscription(sid):\n                progress = "电影已确认转存" if is_movie else f"已完成 {done}/{total}"\n                logger.warning("【光鸭转存助手】【完成】#%s %s %s，但 MoviePilot 完成流程后订阅仍存在", sid, getattr(latest, "name", ""), progress)\n                return False\n            self._clear_completion_guard(sid)\n            self._remove_selected_subscription(sid)\n            if is_movie:\n                logger.info("【光鸭转存助手】【完成】#%s %s 电影已确认转存/媒体库存在；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""))\n            else:\n                logger.info("【光鸭转存助手】【完成】#%s %s 已完成 %s/%s，剩余 0；已通过 MoviePilot 官方流程移入订阅历史并从活动订阅移除", sid, getattr(latest, "name", ""), done, total)\n            return True\n        except Exception:\n            logger.exception("【光鸭转存助手】【完成】#%s %s 执行 MoviePilot 官方完成流程失败", sid, getattr(subscribe, "name", ""))\n            return False\n'''
replace_once(old_finish, new_finish, 'movie completion function')

# 成功转存后如果已经完成订阅，通知文案明确说“已移入历史”。
old_status = '''                    "状态：部分转存完成，剩余保持转存路线等待下轮" if partial else "状态：增量转存已确认完成",\n'''
new_status = '''                    ("状态：电影/剧集目标已完成，订阅已移入历史" if completed_subscription else ("状态：部分转存完成，剩余保持转存路线等待下轮" if partial else "状态：增量转存已确认完成")),\n'''
replace_once(old_status, new_status, 'completion notification status')

old_return = '''            return {"success": True, "handled": True, "message": f"增量转存成功，本次新增 {len(unique_paths)} 个文件", "new_count": len(unique_paths), "target_path": target_path, "remaining": remaining_due_to_cap}\n'''
new_return = '''            return {"success": True, "handled": True, "completed": completed_subscription, "message": (f"转存成功，本次新增 {len(unique_paths)} 个文件；订阅已完成并移入历史" if completed_subscription else f"增量转存成功，本次新增 {len(unique_paths)} 个文件"), "new_count": len(unique_paths), "target_path": target_path, "remaining": remaining_due_to_cap}\n'''
replace_once(old_return, new_return, 'completion result message')

src.write_text(text, encoding='utf-8')

test_path = Path('tests/v3/guangyatransferassistant/test_plugin_contract.py')
tests = test_path.read_text(encoding='utf-8')
addition = r'''


def test_movie_completion_uses_confirmed_video_or_media_library_and_official_flow():
    assert '_is_movie_subscription' in text
    assert '_movie_transfer_confirmed' in text
    helper = text.split('    def _movie_transfer_confirmed(', 1)[1].split('    def _finish_subscription_if_complete(', 1)[0]
    assert 'transfer_inventory' in helper
    assert '_is_video(path)' in helper
    assert 'DownloadChain().get_no_exists_info' in helper
    finish = text.split('    def _finish_subscription_if_complete(', 1)[1].split('    def _remove_selected_subscription(', 1)[0]
    assert 'is_movie = self._is_movie_subscription(subscribe)' in finish
    assert 'if not self._movie_transfer_confirmed(subscribe):' in finish
    assert 'SubscribeChain().finish_subscribe_or_not' in finish
    assert 'force=True' in finish
    flow = text.split('    def _try_transfer_subscription(', 1)[1].split('    def _target_path(', 1)[0]
    assert 'pre_channel_state = self._channel_state_for_subscription(subscribe, entries)' in flow
    assert 'if self._finish_subscription_if_complete(subscribe, channel_state=pre_channel_state):' in flow
    assert '订阅已完成并移入历史' in flow
'''
if 'test_movie_completion_uses_confirmed_video_or_media_library_and_official_flow' not in tests:
    tests += addition

test_path.write_text(tests, encoding='utf-8')
