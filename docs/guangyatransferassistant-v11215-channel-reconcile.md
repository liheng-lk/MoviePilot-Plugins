# GuangYaTransferAssistant v1.12.15 候选验收

## 实机问题

频道或 7 天缓存已经存在当前订阅可用资源，但严格频道游标只把“本轮新增消息”作为事件。首次游标建立、插件重启/bootstrap 或一次性事件未形成时，资源可以存在于缓存而已有订阅不再进入 `channel_event`，表现为“频道有资源但没有转存”。

## 修复边界

v1.12.15 候选只补偿被动事件触发，不改变资源业务规则：

1. 严格频道游标继续判定本轮新增消息；
2. 5 分钟频道 tick 同时复核 7 天缓存中与活跃固定分流订阅匹配的可执行资源；
3. 只有订阅仍存在真实未覆盖缺口时才补偿触发；
4. 缓存条目必须实际包含 GuangYa 分享、Xunlei、Magnet 或 ED2K，title-only 和 stale 条目不能触发；
5. 补偿继续进入既有 `频道新增资源 -> channel_event`，不得主动访问 GYING、不得消耗外部搜索冷却；
6. TV 最终写盘仍必须满足 `MoviePilot library missing ∩ logical/fact missing - reservation - other source claims`；
7. GuangYa/Xunlei/Magnet/ED2K 继续满足不可分割物理文件 `actual episodes ⊆ allowed missing`；
8. 来源优先级仍为 `观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`；Magnet/ED2K 继续使用光鸭原生 cloudcollection。

## 候选测试

首次标准 PR CI 暴露的 4 个失败均为历史测试把 `ManualCheck -> CoreFinal v1.12.14` 直接继承关系写死；新增的 v1.12.15 动态行为测试全部通过。随后一次性迁移仅将历史链断言更新为：

`ManualCheck -> ChannelReconcile v1.12.15 -> CoreFinal v1.12.14 -> Core v1.12.14 -> Xunlei Fence v1.12.13 -> Alias v1.12.12 -> Season Fence v1.12.10`

迁移工作流在提交前运行 95 个根单测和 GuangYaTransferAssistant 全合同，并在成功后自删除。

公开版本在正式 PR CI 通过前继续保持 `1.12.14 / 20260905-r60`。
