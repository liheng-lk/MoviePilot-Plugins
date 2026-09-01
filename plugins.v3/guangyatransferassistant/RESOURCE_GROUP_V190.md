# v1.9.0 ResourceGroup / Episode Resolver 需求与验收

## 问题定义

同一频道帖子可能同时提供光鸭分享、Magnet、ED2K。如果按“来源”独立调度，会出现同一集被直接转存和云添加重复获取。另一个风险是整季 Magnet 只缺几集时整包保存，以及发布组命名不统一导致错误选集。

## 最终需求

1. 同一 Telegram 消息是一个 ResourceGroup；光鸭分享、Magnet、ED2K 是候选获取方式，不是三个独立媒体资源。
2. 先以 MoviePilot 订阅真实缺集为目标，再决定来源；同等满足规则时 `GuangYa Share > Magnet > ED2K`。
3. 光鸭直接转存已提交但尚未落盘的集数必须 reservation，占用期间禁止为同一集创建 Magnet/ED2K 云添加。
4. 分享没有覆盖缺集、明确失败或不满足规则时，剩余缺集才能进入 Magnet；Magnet 不可用时再回退 ED2K。
5. Magnet 必须先 `resolve_res`，只把缺集对应的高置信 `fileIndexes` 传入 `create_task`。不得先整包云添加再删除多余文件。
6. 同一 Magnet 覆盖多个缺集时，一个 task 选择多个文件；不得按集重复创建多个相同 BTIH 任务。
7. ED2K 按文件链接判断，只提交能映射到当前缺集的文件。
8. 多集封装视频是不可拆单文件，可覆盖多个 episode；插件只做文件级选择，不做视频切割。
9. 集号识别必须支持明确格式、中文格式、弱数字命名、发布组格式、Season 上下文、包级序列、特别篇和长篇动画绝对集号，并排除年份/分辨率/编码数字。
10. `A.mkv/B.mkv/C.mkv` 等没有可靠映射证据的文件禁止按排序猜集号。
11. 低置信来源进入 `needs_review`，不创建云添加任务，不整包误存。
12. 字幕只跟随已选剧集；弱字幕仅允许跟随同目录唯一已选视频。
13. Magnet/ED2K 仍只使用光鸭 cloudcollection；不得重新引入 MoviePilot downloader、qBittorrent、Transmission、Aria2 或 ED2K Bridge。
14. 已有 taskId 的任务继续遵守 v1.8 防重复规则：只 poll/retry 现有服务端任务，永不二次 create_task。
15. 外部资源的分辨率/质量等订阅规则在 `resolve_res` 后、`create_task` 前基于真实文件列表校验，避免帖子文本与真实发布信息不一致。
16. 只含 Magnet/ED2K、没有光鸭分享链接的频道消息也必须进入索引。
17. 路由名单异步持久化不能覆盖 v1.8/v1.9 新配置。
18. 状态页/API 要能查看 ResourceGroup 决策、未覆盖剧集和 needs_review。

## 状态模型

```text
Telegram / Viewing
        ↓
ResourceGroup
        ↓
subscription missing episodes
        ↓
GuangYa pending reservation
        ↓
uncovered episodes
        ↓
Magnet candidate → resolve → rule check → episode selection → create_task
        ↓ fail/review
ED2K candidate → rule check / episode map → create_task
```

外部来源状态：

```text
new/retry
  ↓
dispatching
  ↓
submitted/queued/waiting
  ↓
completed

解析不可靠 → needs_review
规则不匹配/最终失败 → failed → 下一候选
```

## Episode Resolver 置信度

默认自动阈值 `0.90`。

- `1.00`：S01E05、EP05、1x05、第5集/话、明确区间、多 E、SP/OVA/OAD。
- `0.96`：弱命名与频道明确 episode hint 一致。
- `0.92`：弱数字位于连续包序列中。
- `0.90`：弱数字有明确 Season 上下文。
- `<0.90`：只作为诊断，禁止自动选择。

## 验收场景

- 帖子同时给分享 + Magnet + ED2K，只产生一套按缺集划分的执行计划。
- 缺 E03/E05/E06，分享覆盖 E03，Magnet 覆盖 E01-E08：分享仅转 E03，Magnet 仅选择 E05/E06。
- 分享 E03 正在落盘时 Magnet 不得选择 E03。
- Magnet 包含 `sample.mkv` / 花絮 / unknown，不得随 E05 一起选择。
- `01.mkv…06.mkv` 在 Season/连续包上下文可拆；A/B/C 不拆。
- `Show.S01E05E06.mkv` 缺 E06 时选择一个文件，不进行物理切割。
- `Show.2026.1080p.H265.10bit.mkv` 不得识别出错误 episode。
- Magnet 解析后不满足订阅 2160P 等规则时不 create_task，并允许后续候选接管。
- taskId 存在时重启/重试不得二次 create_task。
