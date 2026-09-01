# 光鸭转存助手

MoviePilot V3 固定分流与多来源订阅插件。Telegram 频道、观影 GYING、Magnet/ED2K 搜索接口发现的候选最终都绑定到同一个 MoviePilot 订阅状态，不建立第二套追剧进度；Magnet/ED2K 始终交给光鸭原生 cloudcollection，不经过 MoviePilot 下载器。

## v1.9.2：配置页与外部资源提供器

v1.9.2 不再把 legacy、固定分流、多来源、ResourceGroup 各层配置逐层追加到一个长表单。最终配置页固定为四个区域：

- **基础**：插件开关、固定光鸭订阅、目标目录、媒体文件限制、进度同步、通知等；
- **资源来源**：频道地址、观影 GYING、Magnet/ED2K 搜索 API；
- **资源决策与云添加**：来源优先级、自动候选、Episode Resolver 置信度、光鸭云任务轮询与重试；
- **高级**：历史页数、扫描上限、频道刷新、连载保护等低频参数。

旧表单仍用于取得 MoviePilot 动态订阅列表和光鸭目录选项，但旧卡片和重复提示不会再返回前端。

### 观影 GYING

配置页新增：

- `观影地址`，默认 `https://www.gying.org`，域名变化时可以直接修改；
- `登录路径`，默认 `/login`；
- `用户名 / 邮箱`；
- `密码`；
- `Cookie`。

如果配置 Cookie，插件优先使用 Cookie。没有 Cookie、但填写用户名和密码时，会尝试识别标准 HTML 登录表单并登录；若站点存在验证码、滑块或非标准登录流程，则不会尝试绕过验证，而是提示使用已正常登录浏览器取得的 Cookie。

观影搜索流程：

`MoviePilot 缺集 -> GYING 搜索 -> downurl 资源 -> Magnet/ED2K 候选 -> ResourceGroup -> 光鸭云添加`

观影用户名、密码、Cookie 不会出现在状态页和 `/providers/search`、`/providers/test` 返回中。

### Magnet / ED2K 搜索接口

配置项“磁力 / ED2K 搜索接口”支持多行，每行格式：

`名称|类型|地址|密钥`

支持类型：

- `tgsearch`：tg-search 风格 JSON 搜索接口；
- `limitless`：Limitless/相似 `kw` 参数 JSON 接口；
- `json`：通用 `q` 参数 JSON 接口；
- `torznab`：Torznab `t=search&q=` XML 接口。

插件只从返回内容中提取合法 `magnet:?xt=urn:btih:...` 和 `ed2k://|file|...|/`，随后进行去重、媒体标题匹配和订阅绑定。API Token 只作为请求凭据使用，不会回显到资源状态 API。

频道候选优先执行；只有频道没有产生可安全执行的候选、且订阅仍存在缺集时，才会自动调用已启用的外部搜索提供器补充候选。外部搜索不会绕过 ResourceGroup、订阅质量规则、缺集拆包或 taskId 防重复保护。

提供两个诊断 API：

- `GET /api/v1/plugin/GuangYaTransferAssistant/providers/search?keyword=...`
- `POST /api/v1/plugin/GuangYaTransferAssistant/providers/test`

## v1.9.1：状态页重构

最终状态页不再拼接 legacy、固定分流、自检、多来源云添加和 ResourceGroup 的多层诊断卡。首页只有总览、当前状态、需要处理、正在处理、系统状态五个区域；等待新资源、ResourceGroup 尚未覆盖和自动重试属于正常等待，不再堆成黄色警告。

首页只保留三个操作：**刷新频道、刷新云任务、运行自检**。

轻量汇总接口：

`GET /api/v1/plugin/GuangYaTransferAssistant/status/overview`

完整 ResourceGroup 计划：

`GET /api/v1/plugin/GuangYaTransferAssistant/resource/plan`

## ResourceGroup 决策

同一频道消息中的光鸭分享、Magnet 和 ED2K 作为一个 `ResourceGroup`。MoviePilot 先给出真实缺集，再按以下优先级选择唯一执行路径：

`光鸭直接转存 > Magnet 光鸭云添加 > ED2K 光鸭云添加`

光鸭分享已经提交、等待落盘的剧集会进入 reservation；同一集不会同时再启动 Magnet/ED2K。外部云任务的 `target_episodes` / `resolved_episodes` 也会占位，防止其它来源重复执行。

## 只保存真正缺少的剧集

电视剧先读取 MoviePilot 当前真实缺集：

- 光鸭分享用 `fileIds` 做文件级增量转存；
- Magnet 先 `resolve_res` 获取种子文件列表，只把目标缺集对应的 `fileIndexes` 传给 `create_task`；
- ED2K 通常一条链接对应一个文件，只提交可映射到缺集的链接；
- 一个 Magnet 同时覆盖 E05/E06 时创建一个云添加任务并选择两个文件；
- sample、花絮、无法确认集号的视频不会顺带保存；
- `S01E05E06.mkv` 等多集封装按一个不可物理拆分文件处理。

## Episode Resolver

解析器支持 `S01E05`、`S01EP05`、`1x05`、`EP05`、`E05-E06`、`E05E06`、`第5集`、`第5话`、SP/OVA/OAD，以及具有足够上下文的 `05.mkv`、`05~4K`、`Show.Name.05.2160p` 等弱命名。

年份、分辨率、编码数字如 `2026`、`1080`、`2160`、`264`、`265`、`266` 会被排除。`A.mkv / B.mkv / C.mkv` 不按文件顺序猜集。

自动拆包默认置信度为 `0.90`。低于阈值进入 `needs_review`，不会为了尽量保存而整包误存。

## Magnet / ED2K 使用光鸭原生云添加

Magnet 与 ED2K **不交给 MoviePilot 下载器**。插件复用 `光鸭云盘助手 (ShukGuangYaDisk)` 的登录态和目标目录，调用：

`resolve_res -> create_task -> list_task -> 完成/原生重试`

核心接口：

- `/cloudcollection/v1/resolve_res`
- `/cloudcollection/v1/create_task`
- `/cloudcollection/v1/list_task`
- `/cloudcollection/v2/retry_task`

不需要 qBittorrent、Transmission、Aria2 或 ED2K Bridge。已有 `taskId` 的来源只轮询/原生重试现有任务，重启后也不会重复 `create_task`。

## 订阅规则与固定分流

Magnet/ED2K 的真实发布名、分辨率可能只有 `resolve_res` 后才能确认，因此会在光鸭解析文件列表以后、`create_task` 以前重新执行 MoviePilot 的 include/exclude、分辨率、质量、特效等规则。

未接管订阅仍使用 MoviePilot 原生路线；已接管或绑定外部来源的订阅，MoviePilot 原生搜索、RSS 匹配和最终下载提交由硬门禁阻断。网络异常或资源暂缺时也不会静默回退本地下载器。

## 频道与手动观影接入口

默认频道：

- `https://tgm.li668.asia/regengguangya`
- `https://tgm.li668.asia/yunpanguangya`

频道消息可以只有光鸭分享、只有 Magnet/ED2K，或三类来源同时存在。

已有手动来源入口继续保留：

`POST /api/v1/plugin/GuangYaTransferAssistant/viewing/ingest`

用于把已经取得的 Magnet/ED2K 直接绑定到已有 MoviePilot 订阅。

## 配置持久化

固定路线异步写盘时会同时保存原生云添加、ResourceGroup/Episode Resolver、观影和 Magnet API 配置，避免热重载后被 legacy 配置覆盖。

## 依赖

需要安装并登录同仓库的 `光鸭云盘助手 (ShukGuangYaDisk)`。本插件复用其运行态客户端、Token 刷新、目录创建、分享转存和 cloudcollection 能力，不保存第二份光鸭登录凭据。
