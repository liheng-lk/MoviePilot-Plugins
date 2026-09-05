# GuangYaTransferAssistant v1.12.15 发布验收

## 实机问题

频道或 7 天缓存已经存在当前订阅可用资源，但严格频道游标只把“本轮新增消息”作为事件。首次游标建立、插件重启/bootstrap 或一次性事件未形成时，资源可以存在于缓存而已有订阅不再进入 `channel_event`，表现为“频道有资源但没有转存”。

## 修复边界

v1.12.15 只补偿被动事件触发，不改变资源业务规则：

1. 严格频道游标继续判定本轮新增消息；
2. 5 分钟频道 tick 同时复核 7 天缓存中与活跃固定分流订阅匹配的可执行资源；
3. 只有订阅仍存在真实未覆盖缺口时才补偿触发；
4. 缓存条目必须实际包含 GuangYa 分享、Xunlei、Magnet 或 ED2K，title-only 和 stale 条目不能触发；
5. 补偿继续进入既有 `频道新增资源 -> channel_event`，不得主动访问 GYING、不得消耗外部搜索冷却；
6. TV 最终写盘仍必须满足 `MoviePilot library missing ∩ logical/fact missing - reservation - other source claims`；
7. GuangYa/Xunlei/Magnet/ED2K 继续满足不可分割物理文件 `actual episodes ⊆ allowed missing`；
8. 来源优先级仍为 `观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`；Magnet/ED2K 继续使用光鸭原生 cloudcollection。

## 新订阅频道预热

新增订阅固定执行 `强刷全部配置频道 -> 等待单飞刷新完成 -> 写入 7 天 cache -> 匹配新订阅`。若增量刷新后仍未命中且频道健康，再按配置 `history_pages` 有界回溯当前 Telegram cursor 之前的历史页。回溯复用既有频道解析器，只调用 cache 写入，不修改 `channel_cursors`，也不生成 `_channel_new_entries_v1115`，因此旧消息不会被伪造成新事件。频道失败或退避时不绕过 Reliability 继续历史抓取，并明确记录‘本地缓存未命中’不等于‘频道没有资源’。

## 发布测试

首次标准 PR CI 暴露的 4 个失败均为历史测试把 `ManualCheck -> CoreFinal v1.12.14` 直接继承关系写死；新增的 v1.12.15 动态行为测试全部通过。随后一次性迁移仅将历史链断言更新为：

`ManualCheck -> ChannelReconcile v1.12.15 -> CoreFinal v1.12.14 -> Core v1.12.14 -> Xunlei Fence v1.12.13 -> Alias v1.12.12 -> Season Fence v1.12.10`

迁移工作流在提交前运行 95 个根单测和 GuangYaTransferAssistant 全合同，并在成功后自删除。

公开版本：`1.12.15 / 20260906-r62`。
