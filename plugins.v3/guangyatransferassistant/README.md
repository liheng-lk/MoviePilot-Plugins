# 光鸭转存助手

MoviePilot V3 专用的固定分流与多来源订阅插件。Telegram 频道中的光鸭分享、Magnet、ED2K，以及“观影”转入的 Magnet/ED2K，最终都绑定到同一个 MoviePilot 订阅状态，不建立第二套追剧进度。

## v1.9.0：ResourceGroup 决策

频道里一条消息可能同时出现光鸭分享链接、Magnet 和 ED2K。v1.9.0 不再把它们视为三个互不相关的任务，而是先合并为一个 `ResourceGroup`：

```text
MoviePilot 订阅真实缺集
        ↓
Telegram 消息 / 观影来源
        ↓
ResourceGroup
├─ GuangYa Share
├─ Magnet
└─ ED2K
        ↓
候选决策
        ↓
唯一执行路径
```

同等满足订阅规则时默认优先级为：

`光鸭直接转存 > Magnet 光鸭云添加 > ED2K 光鸭云添加`

光鸭分享已经提交并等待落盘的剧集会进入 reservation；同一集不会同时再启动 Magnet/ED2K。光鸭分享明确失败、没有覆盖当前缺集或不满足订阅规则后，剩余缺集才交给后续候选。

## 只保存真正缺少的剧集

电视剧先读取 MoviePilot 当前真实缺集，再在资源内部做文件级选择：

- 光鸭分享继续使用成熟的 `fileIds` 增量转存，只转需要的文件；
- Magnet 先调用 `resolve_res` 获取种子文件列表，再把高置信匹配缺集的 `fileIndexes` 传给 `create_task`；
- ED2K 通常一个链接对应一个文件，只提交能映射到缺集的链接；
- 同一个 Magnet 若同时覆盖 E05/E06，会创建一个云添加任务并选择两个文件，而不是每集创建一个任务；
- `sample`、花絮、无法确认集号的视频不会因为与正确剧集处于同一包就顺带保存；
- 多集封装文件（例如 `S01E05E06.mkv`）是不可物理拆分的单文件，缺 E06 时会选择这个文件，但不会尝试切割 MKV。

## Episode Resolver

v1.9.0 增加统一的置信度剧集识别器。它不是简单从文件名抓数字，而是综合明确格式、Season 上下文、整包连续序列和频道集数提示。

高置信格式包括 `S01E05`、`S01EP05`、`1x05`、`EP05`、`E05-E06`、`E05E06`、`第5集`、`第5话`、SP/OVA/OAD 等。`05.mkv`、`[05].mkv`、`Show - 05`、`05~4K`、`Show.Name.05.2160p` 等弱命名只有获得 Season、连续包或明确频道提示等额外证据后才允许自动选择。

解析器会排除年份、分辨率和编码等噪声数字，例如 `2026`、`1080`、`2160`、`264`、`265`、`266`。`A.mkv / B.mkv / C.mkv` 不会按文件顺序猜成 E01/E02/E03。长篇动画的四位绝对集号也可以在明确上下文下识别。

自动拆包默认置信度阈值为 `0.90`。低于阈值的来源进入 `needs_review`，不会为了“尽量下载”而整包误存。

字幕只在两种情况下跟随：字幕本身能高置信映射到已选择剧集，或者同一目录只有一个已选择视频且字幕无集号。不会把其它集字幕一起带入。

## Magnet / ED2K 使用光鸭原生云添加

Magnet 与 ED2K **不交给 MoviePilot 下载器**。插件复用 `光鸭云盘助手 (ShukGuangYaDisk)` 的登录态和目标目录，直接调用光鸭云盘自带的 cloudcollection：

`resolve_res -> create_task -> list_task -> 完成/原生重试`

使用的核心接口：

- `/cloudcollection/v1/resolve_res`
- `/cloudcollection/v1/create_task`
- `/cloudcollection/v1/list_task`
- `/cloudcollection/v2/retry_task`

因此不需要 qBittorrent、Transmission、Aria2，也不需要 ED2K Bridge。来源已经获得 `taskId` 后只轮询或原生重试现有任务，进程重启也不会重复 `create_task`。

## 订阅规则

光鸭分享沿用原有分享文件检查。Magnet/ED2K 的真实发布名、分辨率等信息可能只有 `resolve_res` 后才知道，因此 v1.9.0 不再仅凭 Telegram 帖子文本提前淘汰外部候选，而是在光鸭解析文件列表以后、创建云添加任务以前再次执行 MoviePilot 订阅的 include/exclude、分辨率、质量、特效等规则。解析后不匹配会直接转向下一候选，不创建云添加任务。

## 固定分流与防重复

未接管的订阅完全保持 MoviePilot 原生订阅路线。已接管或绑定外部来源的订阅，MoviePilot 原生搜索、RSS 匹配和最终下载提交都由既有硬门禁阻断；Telegram 暂时不可用、光鸭云添加等待中或网络异常时也不会静默回退本地下载器。

除光鸭分享的 pending reservation 外，Magnet/ED2K 的 `target_episodes` / `resolved_episodes` 也会作为在途占位，同一订阅不会为同一缺集反复创建其它外部任务。

## 频道资源

默认频道：

- `https://tgm.li668.asia/regengguangya`
- `https://tgm.li668.asia/yunpanguangya`

频道消息可以是“光鸭分享 + Magnet + ED2K”，也可以只有 Magnet/ED2K。只含外部链接的消息也会进入频道索引，不会因为没有 `guangyapan.com/s/...` 就被丢弃。

## 观影接入

现有来源接入口保持：

`POST /api/v1/plugin/GuangYaTransferAssistant/viewing/ingest`

推荐传 `subscribe_id` + `uri`；没有订阅 ID 时可用 `title/year` 唯一定位现有 MoviePilot 订阅。当前该接口负责把已经取得的 Magnet/ED2K 送入统一来源状态机；具体“观影搜索提供器”后续只需要输出候选并接入同一个 ResourceGroup planner，不需要重新实现云添加和拆包逻辑。

## 状态与诊断

`GET /api/v1/plugin/GuangYaTransferAssistant/resource/plan` 可以查看最近的缺集决策计划，包括原始缺集、光鸭转存在途占位、外部来源占位、仍未覆盖剧集和已选择候选。状态页顶部会提示 `needs_review` 数量，便于发现无法安全拆包的来源。

来源列表仍会脱敏 Magnet tracker 参数。高级诊断继续保留固定分流健康、频道索引、自检、转存任务、原生云添加任务和失败原因。

## 配置持久化

v1.9.0 收口了固定路线异步写盘与多来源配置的组合：路由名单触发配置持久化时，会同时保存 v1.8 的原生云添加配置和 v1.9 的 ResourceGroup/Episode Resolver 配置，避免热重载后恢复成默认值。

## 依赖

需要安装并登录同仓库的 `光鸭云盘助手 (ShukGuangYaDisk)`。本插件复用其运行态客户端、Token 刷新、目录创建、分享转存和 cloudcollection 能力，不保存第二份光鸭登录凭据。
