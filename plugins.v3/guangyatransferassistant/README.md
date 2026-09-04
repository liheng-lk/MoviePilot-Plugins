## v1.11.2：频道 ED2K 自动云添加

- 频道扫描同时识别光鸭分享、Magnet 与 ED2K；同一消息继续按 ResourceGroup 决策。
- 若直接转存不能覆盖当前缺集，而频道中有合适 ED2K，插件会调用光鸭原生 `cloudcollection` 云添加。
- ED2K 单文件允许先 `resolve_res`，再依据真实文件名和频道集号确认缺集；不确认集号则进入保护状态，不整包误存。
- ED2K 完成后会回填实际集号并立即更新 MoviePilot 订阅进度，与迅雷秒传/直接转存/Magnet 共用同集终止栅栏。

# 光鸭转存助手


## v1.12.8：/gysub 消息入口 hotfix

- 最终插件类显式注册 routing `PluginAction` 桥，`/gysub`、`/gystatus`、`/gynative` 不再依赖隐式继承事件绑定。
- `/gysub` 参数合法后立即回复“已收到光鸭直订请求”，再执行 TMDB 识别和订阅创建；上游变慢时也不会再无反馈。
- 事件处理异常会记录 `【消息命令v1.12.8】` 并尽量向原消息通道回传失败信息。
- 不改 v1.12.7 的资源门禁、拆包、迅雷 JSON 或来源优先级。

## v1.12.7：资源找到但未提交光鸭修复

- TV S02+：系列首播年份与本季发行年份不同不再直接误杀；必须同时满足正确季号与剧集结构。
- 合法别名：GYING 搜索标题命中订阅，且真实分享顶层名与内部文件名自洽、年/季无冲突时允许安全桥接；不做模糊猜测。
- 拆包恢复：Magnet/ED2K 的 `needs_review` 在缺集/季/目标证据变化时立即重评，证据不变每 6 小时最多复核一次。
- 新增 `【拆包v1.12.7】` 日志，一次显示 `missing / reserved / target / resolved / indexes / ambiguous`，便于直接定位“找到了为什么没执行”。
- 来源优先级与终态安全栅栏不变：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。

## v1.12.6：当天更新剧 10 分钟快速追更

- AiringDue 从每 60 分钟唤醒改为每 10 分钟唤醒，缩短资源刚发布后的发现延迟。
- 只有 TV/动漫的 `airing_pull` 使用 10 分钟检索窗口；电影继续 60 分钟。
- 10 分钟只是调度时钟，真正搜索仍要求当前存在 `due_uncovered`，且没有 reservation/source claim；已入库、已在途和非更新日不会打外部资源站。
- GYING 同查询缓存只有 120 秒，小于快追窗口；上一轮没资源不会把下一轮锁在旧空结果里。
- 来源顺序不变：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。
- 5 分钟频道 Push 仍只消费已到达频道资源，不借频道 tick 主动访问 GYING。

## v1.12.5：每小时今日到期媒体完整资源链

- 5 分钟频道 Push 只消费已经到达的频道资源，不再借频道 tick 主动访问 GYING。
- 每小时 AiringDue 只选择今天应播、MoviePilot 仍确认缺失且未被在途任务覆盖的媒体。
- 今日到期媒体使用独立 60 分钟复查窗口，执行顺序保持：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。
- 非更新日剧集不主动访问外部资源站；稳定更新星期可作为排期事实，日历服务异常时采用短退避并保留安全 fallback。
- 每日 04:10 全员复核继续先消费频道，再重算真实剩余缺口并强制补漏。
- 继续保留媒体身份门禁、缺集 planner、跨来源 reservation/source claim 与成功集终止栅栏，避免重复秒传/云添加。

## v1.12.0：逐集上映日历驱动

- 普通后台检查只处理 `due_missing`，尚未进入更新窗口的未来集不访问频道/迅雷/观影。
- 默认在 TMDB 日期当天 20:00 前 12 小时进入提前检查窗口；只有日期精度时明确作为估算时间。
- 每日 04:10 全员补漏仍保留，可发现提前放出或排期数据遗漏。
- 修复旧分享 `handled=True` 误阻断仍缺集的 Magnet/ED2K，以及同订阅外部检索冷却并发竞争。

## v1.10.1：恢复频道资源与独立配置

- 首页重新展示频道索引明细：标题、TMDB、集数、来源、ResourceGroup 可用方式和缓存/过期状态。
- 配置页新增独立“频道资源”区域，频道地址、刷新频率、抓取边界与同帖 Magnet/ED2K 开关集中管理。
- 新增 `/channels/resources` 脱敏只读接口，不返回光鸭分享 URL 或 Magnet/ED2K 原始 URI。

## v1.10.0：控制台、统一搜索与秒传可靠性

- 首页重构为响应式控制台：资源来源健康、固定优先级、搜索缺失资源、秒传预检、一键完整诊断、最近搜索结果和异常/在途任务同屏展示。
- 配置页按“接管与保存 / 资源来源 / 观影与迅雷秒传 / 高级设置”重排，协议细节默认折叠，不改变任何已有配置键。
- `/providers/search` 现在统一返回观影迅雷、Magnet 与 ED2K；`/providers/search/selected` 可直接搜索已选择的固定转存订阅。
- Magnet/ED2K API 自动兼容 `q` / `kw` / `keyword` / `search`，并修正 token 认证头；命中后仍由光鸭原生云添加执行，不经过 MoviePilot 下载器。
- 新增 `/xunlei/flash/preflight`，非破坏性检查观影会话、迅雷 captcha/device/client 与光鸭 userres 运行时。
- 新增 `/diagnostics/full`，一次完成资源来源、固定订阅统一搜索和秒传链路诊断，只返回脱敏状态，不创建文件或下载任务。
- 迅雷 CID 样本严格使用 `stream=True`，单段最多 20KiB；中/尾 Range 被服务器忽略时立即放弃，不下载整文件。
- v1.10.0 增加行为级 dry-run：模拟外部搜索接口参数回退、观影迅雷+Magnet+ED2K 合并、3×20KiB Range 采样和 Range 忽略场景，避免只做字符串合同测试。


MoviePilot V3 固定分流与多来源订阅插件。Telegram 频道、观影 GYING、Magnet/ED2K 搜索接口发现的候选都绑定同一个 MoviePilot 订阅状态，不建立第二套追剧进度。Magnet/ED2K 始终交给光鸭原生 cloudcollection，不经过 MoviePilot 下载器。

## v1.9.6：MoviePilot 最新订阅合同兼容

- `SubscribeChain` 继续走 `app.chain.subscribe` 稳定公开入口。
- `build_subscribe_meta` 按 MoviePilot 最新 V3 架构改从 `app.application.subscription.contract` 导入；早期 V3 保留兼容回退。
- 修复新版 MoviePilot 的 `app.chain.subscribe` 只公开 `SubscribeChain` 后，转存助手在安装/加载阶段直接 `ImportError` 的问题。
- 本次仍只修改光鸭转存助手，不修改光鸭云盘助手。

## v1.9.5：MoviePilot V3 插件管理 SDK 兼容

- `PluginManager` 改用 MoviePilot V3 稳定入口 `app.sdk.plugins`，不再在插件加载期依赖 `app.runtime.extensions.plugin_manager`。
- 光鸭云盘助手运行态优先从 `running_plugins` 取得；旧 `get_plugin_attr` 仅作为 SDK 对象仍提供时的运行期兼容。
- 本次只修改光鸭转存助手，不改光鸭云盘助手；资源优先级和 GYING/迅雷/光鸭原生云添加逻辑不变。

## v1.9.4：观影与迅雷生产完整性收口

v1.9.4 不改变资源优先级，继续固定为：

`观影迅雷秒传 > 光鸭直接转存 > Magnet 光鸭云添加 > ED2K 光鸭云添加`

本版重点处理真实站点与会话的边界，而不是继续增加一套下载路径：

- 中文观影域名与 punycode 统一为同一个节点身份，避免重复验证、重复冷却；
- `星际穿越.com` 等内容节点只作为节点池种子，不写死为唯一地址；旧 `gying.org` 固定默认在自动切换模式下迁移为空，由发布页、备用节点和最近成功节点共同决策；
- 手工观影 Cookie 仅发送给用户绑定的首选节点，自动切换到其他域名不会跨域携带；各节点自己的验证/登录 Cookie 仍独立持久化；
- GYING 搜索只有在零结果时才按 `标题+年份+季 -> 标题+年份 -> 标题` 逐级降级，并在候选同时提供年份时做二次校验；
- Angie/伪 404 等出口阻断会被识别为节点故障并进入 failover，而不是误报“没有资源”；
- 迅雷运行时 Device ID 持久化；captcha_token 与 client/device 作为同一身份维护；没有可复用 token 时可自动调用 `shield/captcha/init`；
- 匿名迅雷分享请求不会携带用户账号 Authorization；`share/file_info` 没拿到 GCID 时，按同 parent_id 再请求 `share/detail?with_audit=false` 精确补 hash；
- 配置页继续保持四区结构，PoW、发布页、备用节点、代理、Device ID、captcha 等协议级参数统一下沉“高级”；状态页继续保持五区紧凑总览。

新增运行诊断：`GET /api/v1/plugin/GuangYaTransferAssistant/xunlei/runtime/status`。公开状态只返回布尔状态与模式，不返回 captcha token、device id、观影 Cookie 或密码。

## v1.9.3：完整观影会话 + 迅雷最高优先级秒传

最终资源优先级固定为：

`观影迅雷秒传 > 光鸭直接转存 > Magnet 光鸭云添加 > ED2K 光鸭云添加`

### 1. 观影不再固定单域名

GYING 会更换内容节点，部分节点可能只是地址发布页、维护页或临时不可用。v1.9.3 建立独立节点池：

- 默认读取 `https://www.gying.page`、`https://gying.si` 等发布/换址入口；
- 支持首选节点，例如 `https://www.星际穿越.com`；
- 支持手动备用节点，每行一个；
- 自动缓存发现的节点与最近成功节点；
- 维护、换址页、阻断、搜索失败节点进入短暂冷却，自动尝试下一节点；
- 中文 IDN 与 punycode 节点都可以使用；
- 节点列表默认缓存 360 分钟，避免每次搜索都访问发布页。

配置页对应字段：`viewing_registry_urls`、`viewing_base_url`、`viewing_node_urls`、`viewing_auto_switch`、`viewing_node_cache_minutes`。

### 2. 浏览器计算验证 / PoW

观影的“正在确认你是不是机器人 / 浏览器安全验证”不是普通账号登录失败。插件保持同一个 `requests.Session` 和浏览器化请求头，当前兼容三类站点计算验证：

1. **远程 PoW**：`GET /res/pow` 取得 `N/x/t`，计算 `y=(y*y)%N` 共 `t` 次，再 `POST /res/pow` 提交 `y`；
2. **内嵌 PoW**：页面直接给出 `id/N/x/t`，完成同样的平方取模后提交 `action=verify&id=...&y=...`；
3. **旧版哈希 challenge**：按 `challenge/diff/salt` 枚举 nonce，并按原顺序提交 `nonce[]`。

验证成功后的 `browser_verified/browser_pow` 与账号登录 Cookie 属于不同状态。插件把同一节点的最新 Cookie 私下保存到 `viewing_session_state` 并在重启后复用，公开 API 不返回 Cookie、密码或 challenge 明文。

此流程只复现站点前端公开执行的计算验证，不绕过账号权限；需要账号访问的内容仍必须使用用户自己的账号密码或合法取得的 Cookie。

### 3. 观影真实接口

最终运行时使用当前 GYING 实际链路：

```text
GET  {node}/
POST {node}/user/login
GET  {node}/search?q={keyword}&type=0&mode=2
GET  {node}/res/downurl/{type}/{id}
```

登录 POST 固定使用站点表单字段 `code/siteid/dosubmit/cookietime/username/password`，以 JSON `code == 200` 判定成功，并在登录后预热 `/mv/wkMn`。

搜索响应不是纯 JSON，影视列表位于 HTML 的 `_obj.search={...};`。插件读取其中的 `title/year/d/i`，再访问 `res/downurl`，从详情 `panlist` 提取真实资源链接。同一个搜索结果缓存 120 秒，Magnet/ED2K Provider 与迅雷秒传共同复用，避免为了两种来源重复打观影站。

诊断 API：

- `GET /api/v1/plugin/GuangYaTransferAssistant/viewing/nodes`
- `POST /api/v1/plugin/GuangYaTransferAssistant/viewing/nodes/refresh`
- `POST /api/v1/plugin/GuangYaTransferAssistant/viewing/session/test`
- `GET /api/v1/plugin/GuangYaTransferAssistant/providers/search?keyword=...`
- `POST /api/v1/plugin/GuangYaTransferAssistant/providers/test`

以上状态接口不会回显观影密码或 Cookie。

### 4. 观影迅雷分享 → 光鸭秒传

从 `panlist` 发现 `https://pan.xunlei.com/s/...` 后，迅雷路径不会把文件下载到 MoviePilot：

1. `/drive/v1/share`：取得 `pass_code_token`；
2. `/drive/v1/share/detail`：递归读取分享文件；
3. `/drive/v1/share/file_info`：必要时补 GCID、MD5、CID/下载链接；
4. MoviePilot 真实缺集 + Episode Resolver + 订阅质量规则筛选文件；
5. 光鸭 userres：`get_res_center_token -> check_can_flash_upload -> get_info_by_task_id`；
6. `get_res_center_token code=156` 直接视为秒传命中；
7. 秒传未命中清理未完成 upload task，继续低优先级来源。

CID 缺失时只读取迅雷文件**头 20KB + 1/3 位置 20KB + 尾 20KB**计算 SHA-1，不下载完整视频。插件不执行 OSS PUT，不进行本地跨盘中转，也不调用 MoviePilot DownloadChain。

迅雷状态接口：

- `POST /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/test`
- `GET /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/state`

## 配置页

最终配置页固定四块：

- **基础**：插件开关、接管订阅、目标目录、媒体限制、进度同步；
- **资源来源**：Telegram、观影节点池/账号/Cookie、PoW 自动验证、Magnet/ED2K API、迅雷秒传；
- **资源决策与云添加**：来源优先级、Episode Resolver 置信度、光鸭云任务轮询/重试；
- **高级**：历史页数、扫描上限、频道刷新、连载保护。

旧的 `viewing_login_path` 只为了升级兼容继续持久化，不再出现在 UI；真实登录路径固定为 `/user/login`。

### Magnet / ED2K 搜索接口

“磁力 / ED2K 搜索接口”每行格式：

`名称|类型|地址|密钥`

支持 `tgsearch`、`limitless`、`json`、`torznab`。候选仍进入 ResourceGroup，并继续执行 MoviePilot 订阅规则、缺集拆包和 taskId 防重复。

## ResourceGroup 与缺集拆包

迅雷秒传是 ResourceGroup 之前的最高优先级预检。它未覆盖的目标才进入：

`光鸭直接转存 > Magnet > ED2K`

电视剧始终先读取 MoviePilot 当前真实缺集：

- 迅雷分享：文件清单进入同一 `_planner_file_selection`，只秒传可靠映射到缺集的文件和字幕；
- 光鸭分享：只提交目标 `fileIds`；
- Magnet：`resolve_res` 后只把缺集对应 `fileIndexes` 交给 `create_task`；
- ED2K：只提交映射到缺集的链接；
- 同一个 Magnet 覆盖多个缺集时只建立一个光鸭任务；
- sample、花絮、无法确认集号的视频不顺带保存；
- `S01E05E06.mkv` 作为一个不可物理拆分文件处理。

秒传成功、光鸭分享等待落盘和 Magnet/ED2K 已创建任务都会形成 reservation，阻止后续来源重复获取相同剧集。

## Episode Resolver

支持 `S01E05`、`S01EP05`、`1x05`、`EP05`、`E05-E06`、`E05E06`、`第5集`、`第5话`、SP/OVA/OAD，以及有足够上下文的 `05.mkv`、`05~4K`、`Show.Name.05.2160p`。

`2026/1080/2160/264/265/266` 等规格数字会排除；`A.mkv / B.mkv / C.mkv` 不按文件顺序猜集。自动拆包默认置信度 `0.90`，低于阈值进入 `needs_review`，不会整包误存。

## Magnet / ED2K：光鸭原生云添加

Magnet/ED2K 继续复用 `光鸭云盘助手 (ShukGuangYaDisk)` 登录态与目录，调用：

`resolve_res -> create_task -> list_task -> 完成/原生重试`

接口为 `/cloudcollection/v1/resolve_res`、`/cloudcollection/v1/create_task`、`/cloudcollection/v1/list_task`、`/cloudcollection/v2/retry_task`。已有 `taskId` 只轮询/原生重试，重启后不重复 `create_task`。

## 固定分流

未接管订阅仍使用 MoviePilot 原生路线；已接管订阅的 MoviePilot 原生搜索、RSS 匹配和最终下载提交由硬门禁阻断。网络异常、观影节点不可用或资源暂缺时也不会静默回退本地下载器。

## 依赖与生产烟测

需要安装并登录同仓库的 `光鸭云盘助手 (ShukGuangYaDisk)`。本插件复用其运行时客户端、Token 刷新、目录创建、分享转存、userres 秒传和 cloudcollection 能力，不保存第二份光鸭登录凭据。

CI 可以覆盖协议解析、PoW 算法、节点切换、隐私边界、缺集筛选和秒传调用契约；**真实 GYING 账号登录 → 搜索 → 迅雷分享 → 光鸭账号秒传**仍需在实际 MoviePilot 环境用测试账号/Cookie 做生产烟测，因为站点节点、出口与会话验证会动态变化。

## v1.12.9：电影精确 TMDB 官方别名桥接

- 修复电影在观影已经命中，但迅雷真实资源使用英文原名/官方原名时被最终媒体身份门禁误杀的问题。
- 仅当订阅具备明确 TMDB 身份时，通过 MoviePilot `MediaChain.recognize_media` 按同一 TMDB ID 读取官方 `title/en_title/original_title/original_name` 等字段作为可信别名。
- 返回 TMDB ID 或年份与订阅冲突时不采纳别名；电影资源出现季号仍按原门禁拒绝。
- 不使用编辑距离或模糊标题救回，因此不会因相似片名放宽跨媒体安全边界。
- 典型修复场景：订阅中文名“失控陪审团”，真实资源 `Runaway.Jury.2003...`。
