# 光鸭转存助手

MoviePilot V3 专用固定分流与多来源订阅插件。Telegram 频道中的光鸭分享、Magnet、ED2K，以及“观影”转入的 Magnet/ED2K，最终都绑定到同一个 MoviePilot 订阅状态，不建立第二套追剧进度。

## v1.9.1：状态页重构

旧状态页的问题不是缺信息，而是信息太多：legacy、固定分流、自检、多来源云添加、ResourceGroup 等不同层都在 `get_page()` 中追加自己的卡片，导致正常状态、异常、任务、历史和调试信息混在一起。

v1.9.1 把最终状态页收口成单一展示层，不再拼接旧版多层诊断卡。首页固定只有 5 个区域：

1. **光鸭转存助手总览**：只告诉当前是否正常、最近频道刷新时间和资源策略；
2. **当前状态**：固定转存、正在处理、需要处理、等待资源四个数字；
3. **需要处理**：只显示真正需要人工干预的关键异常、云添加失败、低置信 `needs_review` 和失败的光鸭转存任务；
4. **正在处理**：只显示当前在途的光鸭转存和 Magnet/ED2K 云添加，最多 6 条；
5. **系统状态**：汇总光鸭登录、搜索分流、RSS 门禁、最终下载断路器、原生云添加和频道索引状态。

“频道暂时没有资源”“ResourceGroup 尚未覆盖缺集”“自动重试中”都属于正常等待，不再显示成一串黄色警告；完成历史、正常订阅和长日志也不会铺在首页。

首页只保留三个操作：**刷新频道、刷新云任务、运行自检**。

新增轻量汇总接口：

`GET /api/v1/plugin/GuangYaTransferAssistant/status/overview`

完整 ResourceGroup 计划仍可通过：

`GET /api/v1/plugin/GuangYaTransferAssistant/resource/plan`

需要更详细的运行状态时使用“运行自检”，而不是把全部诊断常驻首页。

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

同等满足订阅规则时默认优先级：

`光鸭直接转存 > Magnet 光鸭云添加 > ED2K 光鸭云添加`

光鸭分享已经提交并等待落盘的剧集会进入 reservation；同一集不会同时再启动 Magnet/ED2K。光鸭分享没有覆盖当前缺集或不可用后，剩余缺集才交给后续候选。

## 只保存真正缺少的剧集

电视剧先读取 MoviePilot 当前真实缺集，再在资源内部做文件级选择：

- 光鸭分享使用 `fileIds` 增量转存，只转需要的文件；
- Magnet 先调用 `resolve_res` 获取种子文件列表，再把高置信匹配缺集的 `fileIndexes` 传给 `create_task`；
- ED2K 通常一个链接对应一个文件，只提交能映射到缺集的链接；
- 同一个 Magnet 同时覆盖 E05/E06 时创建一个云添加任务并选择两个文件，而不是每集创建一个任务；
- sample、花絮和无法确认集号的视频不会因为与正确剧集处于同一包就顺带保存；
- 多集封装文件（例如 `S01E05E06.mkv`）作为一个不可物理拆分的文件处理。

## Episode Resolver

统一剧集识别器综合明确格式、Season 上下文、整包连续序列和频道集数提示，而不是简单从文件名抓数字。

支持 `S01E05`、`S01EP05`、`1x05`、`EP05`、`E05-E06`、`E05E06`、`第5集`、`第5话`、SP/OVA/OAD 等。`05.mkv`、`[05].mkv`、`Show - 05`、`05~4K`、`Show.Name.05.2160p` 等弱命名只有获得 Season、连续包或明确频道提示等额外证据后才允许自动选择。

解析器排除年份、分辨率和编码等噪声数字，例如 `2026`、`1080`、`2160`、`264`、`265`、`266`。`A.mkv / B.mkv / C.mkv` 不按文件顺序猜成 E01/E02/E03。

自动拆包默认置信度阈值为 `0.90`。低于阈值的来源进入 `needs_review`，不会为了“尽量下载”而整包误存。

## Magnet / ED2K 使用光鸭原生云添加

Magnet 与 ED2K **不交给 MoviePilot 下载器**。插件复用 `光鸭云盘助手 (ShukGuangYaDisk)` 的登录态和目标目录，直接调用光鸭云盘自带 cloudcollection：

`resolve_res -> create_task -> list_task -> 完成/原生重试`

核心接口：

- `/cloudcollection/v1/resolve_res`
- `/cloudcollection/v1/create_task`
- `/cloudcollection/v1/list_task`
- `/cloudcollection/v2/retry_task`

因此不需要 qBittorrent、Transmission、Aria2，也不需要 ED2K Bridge。来源已经获得 `taskId` 后只轮询或原生重试现有任务，进程重启也不会重复 `create_task`。

## 订阅规则

Magnet/ED2K 的真实发布名、分辨率等信息可能只有 `resolve_res` 后才能确认，因此外部候选在光鸭解析文件列表以后、创建云添加任务以前再执行 MoviePilot 订阅的 include/exclude、分辨率、质量、特效等规则。解析后不匹配就转向下一候选，不创建云添加任务。

## 固定分流与防重复

未接管的订阅完全保持 MoviePilot 原生订阅路线。已接管或绑定外部来源的订阅，MoviePilot 原生搜索、RSS 匹配和最终下载提交都由硬门禁阻断；Telegram 暂时不可用、光鸭云添加等待中或网络异常时也不会静默回退本地下载器。

除光鸭分享 pending reservation 外，Magnet/ED2K 的 `target_episodes` / `resolved_episodes` 也作为在途占位，同一订阅不会为同一缺集反复创建其它外部任务。

## 频道资源

默认频道：

- `https://tgm.li668.asia/regengguangya`
- `https://tgm.li668.asia/yunpanguangya`

频道消息可以是“光鸭分享 + Magnet + ED2K”，也可以只有 Magnet/ED2K。只含外部链接的消息同样进入频道索引。

## 观影接入

现有来源接入口：

`POST /api/v1/plugin/GuangYaTransferAssistant/viewing/ingest`

推荐传 `subscribe_id` + `uri`；没有订阅 ID 时可用 `title/year` 唯一定位现有 MoviePilot 订阅。该接口把已经取得的 Magnet/ED2K 送入统一来源状态机。

## 配置持久化

固定路线异步写盘时会同时保存 v1.8 原生云添加配置和 v1.9 ResourceGroup/Episode Resolver 配置，避免热重载后恢复成默认值。

## 依赖

需要安装并登录同仓库的 `光鸭云盘助手 (ShukGuangYaDisk)`。本插件复用其运行态客户端、Token 刷新、目录创建、分享转存和 cloudcollection 能力，不保存第二份光鸭登录凭据。
