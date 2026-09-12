## v2.1.0-r98 — 单文件统一转存主链（Controlled Real-World Beta）

本版把“功能存在”收口为一条可验证的真实业务链，同时按项目维护要求将插件运行时代码全部集中到唯一的 `__init__.py`。插件目录内出现其它 `*.py` 会直接触发 CI 失败。

### 统一业务主链

```text
MoviePilot 订阅
→ Telegram / GYING 资源发现
→ MoviePilot 媒体身份、年份、Season 与权威缺集匹配
→ 迅雷秒传 > 光鸭分享直转 > Magnet > ED2K
→ 光鸭目标目录真实落盘确认
→ MoviePilot 识别结果优先的最终文件名确认
→ 成功通知
```

四种资源执行方式固定为：

- 迅雷分享：解析分享真实文件 → 生成秒传 JSON → 只选择当前权威缺集 → 光鸭秒传；服务端返回成功不算完成，必须在目标目录确认本次新增文件。
- 光鸭分享：调用光鸭原生分享恢复接口做文件级增量转存；落盘后远端 rename 必须确认，最终文件名没有确认时保持 `pending_verification`，不提前发送成功通知。
- Magnet：使用光鸭原生 `cloudcollection`；任务 completed 后继续确认真实正片和最终文件名。
- ED2K：使用光鸭原生 `cloudcollection`；单文件仍经过真实文件名、缺集与最终落盘门禁。
- 不引入 MoviePilot 普通下载器、qBittorrent、Transmission、Aria2 或本地整文件下载再上传兜底。

### MoviePilot 优先命名

媒体身份以 MoviePilot 识别结果为第一优先级，原资源名只提供技术参数。

电视剧示例：

`幸运女神 - S01E07 - 2160p WEB-DL H265 DDP5.1 HDR10 GROUP.mkv`

电影示例：

`沙丘2 (2024) - 2160p BluRay REMUX DV HEVC TrueHD 7.1 GROUP.mkv`

会尽量保留分辨率、WEB-DL/BluRay/REMUX、H.264/H.265/HEVC/AV1、HDR/DV、音轨及发布组等有效技术标签；标题、年份、Season、Episode 不再接受来源文件名覆盖 MoviePilot 识别结果。

### 成功闭环

本版统一规定：API 返回 success、迅雷秒传接口成功、cloudcollection task completed 都不能单独视为转存成功。成功必须具备当前任务可归因的真实文件证据，并完成最终文件名确认；预先已经存在的同名/同 fileId 文件不会冒充本次落盘。成功通知只在这一闭环完成后发送；除各来源自身的完成状态外，最终入口还使用持久化成功指纹去重，同一成功回执跨轮询/重启不会重复推送。

Telegram 与 GYING 都使用真实解析结构做四来源矩阵回归，均验证可产出 `xunlei / guangya / magnet / ed2k` 并进入同一优先级。发布收口前完整 CI：**GuangYa contract tests 1076 run / 0 failed**。 最终 unified provider evidence、最终命名、真实落盘与 exactly-once 通知合同补齐后：**1084 run / 0 failed**。

### 实机验证边界

上述结果证明代码合同、解析器、状态机和最终插件 harness 均通过自动回归，但不等于已经替代真实 MoviePilot + GYING + 迅雷 + 光鸭账号环境的网络烟测。发布后仍应先用少量真实订阅验证实际 Cookie/PoW、站点节点、迅雷 captcha、光鸭接口和 Emby 扫描延迟；真实日志确认后再扩大订阅范围。

## v2.0.13-r97 — Usability Hardening（Controlled Real-World Beta）

本版本继续作为 **Controlled Real-World Beta** 发布，重点从“功能齐全”转向“真实运行状态可闭环、异常可恢复、用户能看懂”。

### 本版重点
- cloudcollection 服务端已 completed、但 fileName/正片回执不足时不再永久 waiting
- 增加 20 分钟远端正片核验窗口；长期无法确认后转 needs_review 并释放 Episode claim
- Emby 已满足目标时仅解除重复占位，不把媒体库观察伪造成 Magnet/ED2K 成功回执
- daemon source worker 异常会写回 retry/waiting；已有 taskId 时禁止重复 create/retry
- 未验证完成不再写入 completed 健康指标
- 状态页明确显示“远端任务已完成，正在核验正片”及等待时长
- final-plugin E2E 保持零额外依赖，修复 CI 对 pytest 的隐式依赖
- 发布前完整 CI：GuangYa contract tests 1058 run / 0 failed

## v2.0.12-r96 — Episode Runtime Hotfix（Controlled Real-World Beta）

本版本为 **Controlled Real-World Beta**，不是 Stable / 正式稳定版 / 生产稳定版。

### 本版重点
- Library observation ≠ transfer receipt；清理 r95 library-as-receipt 污染并可 reopen
- AiringDue cycle context：同轮 Emby ≤1、MP resolve ≤1
- ED2K no-subfiles 单文件 ambiguous 清除，合法视频可 create_task
- Direct 部分 pending 后同轮继续 GYING Magnet/ED2K 补齐剩余缺集
- GYING search singleflight + 真实 run_id；runtime init ready 门禁
- Final Plugin E2E：Direct E05 → Magnet E07 → ED2K E09

### 仍需实机验证
- 大批真实订阅下 AiringDue / Emby 查询次数
- ED2K / Magnet 远端实际落盘
- Direct→GYING 同轮补齐在复杂 ResourceGroup 下的稳定性
- PanSou verified session 并发

### 发布后优先观察
1. 同一次 AiringDue Emby / MP 是否仍风暴式重复
2. ED2K 单文件是否还会 needs_review
3. Direct 只覆盖部分集后 Magnet/ED2K 是否同轮跟上
4. 第二轮是否零重复 create_task
5. managed 是否仍禁止 native fallback

### 实机红线（出现任一停止扩大 Beta）
错误媒体/错季转存；managed 回落 native；同 episode 批量重复；subtitle-only 被判媒体成功；Emby I/O 风暴 / recursion；未来集提前批量转存。

## v2.0.11-r95 — Episode Integrity Beta（Controlled Real-World Beta）

r95 引入 Emby 实际库驱动补集与统一 Episode Target Resolver；详见历史 changelog。

## v2.0.10 Beta - Controlled Real-World Beta（20260911-r94）

本版本为实机验证测试版（非 Stable Release），冻结已审 `2.0.9-r93` 业务基线。

重点验证：

- MoviePilot 原生订阅日历驱动匹配
- 频道 Raw HTML Resource Inbox
- 隐藏分享链接识别
- GuangYa / Xunlei / Magnet / ED2K 多来源处理
- MoviePilot / Emby 媒体库预检查
- TMDB 强身份确认
- Episode Fence
- managed subscription 原生搜索隔离
- Resource Trace
- 结构化转存失败原因
- 批次状态汇总
- 多来源候选聚合
- Magnet / ED2K / Xunlei 诊断跟踪

建议分阶段小范围实机验证：先 5~10 个 managed subscriptions 人工触发；再观察真实频道增量；再跑至少一个完整 scheduler 周期。确认没有错媒体、错季、重复转存后再扩大。

已知观察项（非 blocker）：episode attempt backoff 真实生产行为；21:00 reconcile 与 external recall 顺序；TGM channel source label 状态区分。欢迎反馈运行日志。

实机红线（出现任一立即回滚到可用的 `2.0.9-r93` 包）：错媒体/错季转存；已存在剧集大量重复转存；managed SID 回退 MoviePilot native search；同一资源反复创建多个任务；不同 Telegram message 密码串线；cursor 前进导致新资源永久漏掉；插件异常影响 MoviePilot 主流程。

## v1.12.26 - 频道标题清洗与剧集名季集命名

- 兼容 `名称：标题(2026） 4K 更新至xx集`、`[剧集·光鸭] 标题 (年份)` 等模板噪声，避免匹配失败直接跳过转存。
- 转存落盘命名改为 `剧集名 SxxExx`（多集 `SxxExx-Eyy`）；电影仅用剧名。
- 覆盖迅雷秒传、Magnet/ED2K 云添加提交名，以及光鸭分享落盘后的远端 rename。

## v1.12.23 - 观影搜索真值与精确候选

- 合法零结果不再误切到 legacy 推荐页；损坏的非空响应仍会兼容回退。
- 订阅搜索在 downurl 前按标题、年份、季号和媒体类型筛选全部卡片，再应用数量上限；默认推荐、近似标题和跨类型卡片不会进入执行链。
- 官方别名全部完成且未命中才报告零候选；中途失败显示“检索未完成”。“我的资源检索”在全局截断前过滤当前订阅，并分开显示来源健康、精确候选和真实入队结果。
- 搜索缓存按订阅身份隔离，同一作用域并发请求合并；Magnet 与迅雷复用已取得的详情快照。

## v1.12.22 - 候选回退与真实调度回执

修复电影首个频道帖子无可执行资源时提前结束、遗漏后续匹配帖子；Provider 跳过仍在冷却的 failed/needs_review 和禁用候选，保留到期重开；频道、Provider、观影自动执行按真实入队回执计数，入队失败不再虚报成功或扣除缺集；统一规划与最终写盘的 completed claim 老化释放，防止旧任务在提交阶段再次阻断真实缺集。保留媒体身份、年份、质量、在途去重与光鸭原生 cloudcollection 门禁。

## v1.12.20 - 频道完整性与实时触发

- 兼容当前 tgm 热更模板 `📺 剧集：标题 (年份) SxxExx`、`📺 动漫：...` 与 `🎬 电影：标题 (年份)`，模板类型、年份、季集号只作为结构化元数据，不再污染严格媒体标题。
- 频道分页只有真正追到刷新前旧游标才允许推进 `channel_cursors`；积压较深时同一轮有界扩大分页，仍未追完则恢复旧游标并记录下一轮 catchup 预算，避免中间消息永久丢失。
- 5 分钟频道 Push、7 天缓存补偿、AiringDue、真实 payload 身份门禁、MoviePilot 权威缺集、reservation/source claim、不可分割物理文件栅栏及 v1.12.18 空目录安全边界全部保持。

## v1.12.19 - 高置信媒体匹配与来源可靠性

- 电影覆盖迅雷、光鸭直接分享、Magnet、ED2K：搜索标题只负责发现，最终执行必须由真实 payload 视频及 MoviePilot/TMDB 可信官方标题证据确认；保留严格双语真实资源桥，不增加模糊救回。
- 剧集/动漫拆分 `requested_episodes`、`candidate_episodes`、`resolved_episodes`、`transfer_episodes`；未 resolve 候选不再提前占用其它来源缺集，真实解析后再次按 MoviePilot 当前权威 missing 与不可分割物理文件做最终过滤。
- Provider 候选先汇总排序再做全局 limit/去重，避免后配置高质量来源被提前截断；普通 API 最多 4 并发，所有同时搜索共享进程级 4 槽预算，GYING 保持独立会话链。
- URL 模板不再重复请求 q/keyword/kw/search；普通 Provider 对最近成功参数名做 6 小时有界学习，失效时继续完整 fallback，不降低召回。
- 来源状态 read-modify-write 使用进程级 `RLock`；质量学习只统计真实成功及资源本身可归因失败，网络/API/目标路径/订阅删除等基础设施问题保持中性。
- 来源优先级保持：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K；Magnet/ED2K 继续使用光鸭原生 `cloudcollection`，不接 MoviePilot 本地下载器。

## v1.12.18 - 空目录生命周期保护

- Magnet/ED2K 在第一次创建目标目录前完成 `resolve_res`，解析/筛选失败不会留下媒体空目录；预解析结果直接复用，不额外重复请求。
- 迅雷、光鸭分享、Magnet/ED2K 只追踪“本次调用前明确不存在”的目录；失败且没有服务端 taskId 时，再次读取远端并确认目录仍为空才允许回收。
- 已有目录、非空目录、目录读取失败、服务端 taskId、pending verification、`/` 与配置保存根目录一律 fail-closed 保留，避免异步迟到文件竞态和误删。
- 待落盘 `_verify_restored_items` 改用 `get_item()` 只读查询；目标目录不存在只报告“尚未落盘”，验证动作自身不再创建目录。
- 不改变 v1.12.17 的结构化资源召回，也不改变媒体身份、年份/Season、权威缺集、reservation/source claim、不可分割物理文件门禁及 `观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K` 优先级。

## v1.12.17 - 结构化资源召回与频道定向搜索

- GYING 使用订阅/TMDB 官方标题、英文名、原名生成最多 8 档有界查询，不再只依赖单一中文展示名。
- 搜索候选先解析 release title，剥离 READNFO、语言、分辨率、来源、编码、字幕和发布组等技术噪声；明确年份、季号或 canonical ID 冲突仍直接拒绝。
- 无年份且只靠第二别名命中的同名候选必须再由 MoviePilot `recognize_by_meta` 确认为同一 TMDB/IMDb 作品，并缓存消歧结果。
- 新订阅、人工检查和主动 Pull 在频道缓存未命中时，对配置 Telegram 频道执行最多 4 档 `?q=` 定向搜索；多频道有界并发，成功/失败分别冷却，避免搜索风暴。
- 定向搜索只补既有 7 天频道 cache/index，不修改 `channel_cursors`，不把历史帖子伪造成新事件；5 分钟 `channel_event` 仍完全被动。
- 最终写盘继续执行 v1.12.13~v1.12.16 的真实 payload 身份、权威缺集、reservation/source claim 与不可分割物理文件硬栅栏；来源优先级不变。

## v1.12.16 - 电影双语真实资源身份修复

- 修复同一电影在观影/迅雷中以‘中文标题 + 第二语言标题’展示、实际视频使用第二语言标题时被误判为跨媒体的问题。
- 仅在 discovery 命中订阅、同一真实分享形成双语闭环、年份精确一致且真实视频精确命中第二语言标题时救回。
- 错误电影、错误年份、纯外文无同分享桥接、电视剧继续拒绝；不使用模糊标题匹配。
- 来源优先级与 v1.12.15 频道预热、v1.12.14 防重复/缺集硬栅栏保持不变。

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

## v1.12.10：迅雷跨季物理资源去重

- 修复同一个真实迅雷分享被同一剧集的多个 Season 订阅同时消费，导致光鸭出现 `01.mp4 / 01(1).mp4` 等重复文件。
- 无明确季号的 TV 整包会先解析完整集号结构；当前季总集数为 32 但资源包实际到 E60 时整包拒绝，不再裁剪 E01-E32 后冒充 S02。
- 同一系列、同一无季号 Xunlei share 在首个真实秒传成功后持久绑定到该 Season；其它 Season 不再重复导入。
- 同系列 Xunlei 主流程串行，关闭 S01/S02 同时越过门禁的竞态；旧成功状态可自动恢复 share claim。
- 显式带 Sxx/Season/第x季 的真实多季包继续由原媒体身份与文件级 planner 拆分；电影、GYING、Magnet/ED2K 和来源优先级不变。

## v1.12.9：电影精确 TMDB 官方别名桥接

- 修复电影在观影已经命中，但迅雷真实资源使用英文原名/官方原名时被最终媒体身份门禁误杀的问题。
- 仅当订阅具备明确 TMDB 身份时，通过 MoviePilot `MediaChain.recognize_media` 按同一 TMDB ID 读取官方 `title/en_title/original_title/original_name` 等字段作为可信别名。
- 返回 TMDB ID 或年份与订阅冲突时不采纳别名；电影资源出现季号仍按原门禁拒绝。
- 不使用编辑距离或模糊标题救回，因此不会因相似片名放宽跨媒体安全边界。
- 典型修复场景：订阅中文名“失控陪审团”，真实资源 `Runaway.Jury.2003...`。

## v1.12.11：/gycheck 人工完整资源检查

- `/gycheck` 不再只是把订阅送入通用后台检查；它现在有独立的人工完整链语义。
- 第一阶段强制刷新一次频道并只消费频道资源；若频道已经覆盖目标，立即终止后续外部访问。
- 若频道命中为 0 或仍未覆盖，重新计算电影待处理事实/剧集真实缺口，然后以 `force=True` 进入完整来源链：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。
- 人工 `force=True` 只绕过 10/60/180 分钟自动检索冷却；媒体身份、年份、质量、Episode Fence、reservation/source claim、迅雷跨季物理资源栅栏全部继续生效。
- 消息回执会明确提示‘频道为 0 不会停止后续观影检索’，避免把频道诊断误解为整条资源链的最终结果。

## v1.12.12：GYING 精确官方别名前置检索

- 修复电影官方英文名只用于‘搜索后身份判断’，却没有进入‘搜索前关键词’的问题。
- 例如 `失控陪审团 (2003)` 会先搜索 `失控陪审团 2003`；当前媒体未命中时，再使用同一 TMDB 身份校验出的 `Runaway Jury 2003`。
- GYING 返回其它影片卡片不再被当成当前媒体搜索成功；只有实际候选通过当前订阅身份判断才停止别名降级。
- 中文首轮已命中时不会多打一轮英文请求；认证、节点或 HTTP 搜索失败时也不会用别名轮询掩盖故障。
- 只接受 MoviePilot 当前订阅精确 TMDB ID + 年份校验后的官方标题，不使用编辑距离、拼音、相似片名等模糊救回。
- 观影迅雷秒传与 GYING Magnet/ED2K 使用相同前置别名语义；最终来源优先级和全部安全门禁不变。
- MoviePilot 原生全局搜索并未把 GYING 注册成 Indexer；本修复覆盖光鸭转存助手自己的统一 Provider 搜索和订阅资源链。


## v1.12.13：迅雷已入库集最终硬栅栏

- 修复实机：MoviePilot 媒体库已有 E01-E09，频道刚补 E10 后，迅雷完整包仍可能把 E01-E06 再次秒传。
- TV 迅雷开始前必须成功读取 MoviePilot 媒体库缺集事实；允许集严格为 `library missing ∩ logical/fact missing - reservation - active claim`。
- 两份强事实允许处于不同刷新时序，但只能通过交集继续收紧。例如媒体库给出 E10-E30、频道成功事实封住 E10，即得到 E11-E30。
- JSON 1.1.3 仍完整生成，但真正 batch import 前再按文件级集号做一次硬过滤；视频只要包含任一非当前缺集，整文件拒绝。
- `E09-E11` 这类横跨“已有 + 缺失”的多集文件按不可分割文件处理，不会为了 E11 顺带重复 E09/E10。
- 若 MoviePilot 媒体库缺集事实无法读取，本轮只禁用迅雷秒传并继续光鸭直接转存、Magnet、ED2K，不以不确定状态冒险写入。
- 电影路径不变；来源优先级仍为：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K。

## v1.12.14：核心资源链统一与最终缺集硬栅栏

- 频道与观影 GYING 现在都可以贡献四类候选：光鸭分享、迅雷分享、Magnet、ED2K；频道迅雷密码只从同一条消息读取，观影光鸭分享以临时 ResourceGroup 进入既有直接转存链，不写入持久 Telegram 索引。
- TV/动漫在中文标题没有当前媒体可用候选时，可按订阅精确 TMDB ID 补充官方 `title/en_title/original_title/original_name` 等可信标题继续检索；不使用编辑距离、拼音或模糊标题猜测。
- TV 最终允许集统一收紧为 `MoviePilot library missing ∩ logical/fact missing - reservation - other source claim`；当前正在提交的 source 不会把自己的 claim 再扣一次。
- 光鸭直接分享、迅雷、Magnet、ED2K 的不可分割视频统一要求 `actual episodes ⊆ allowed missing`。例如只缺 E11 时，单集 E11 可以写入，`E09-E11` 或 `E09-E12` 整文件必须拒绝。
- 搜索卡片/频道标题只作为发现证据；真正提交前重新检查实际分享/resolve 文件。真实标题、年份或 Season 明确冲突时拒绝；`S01E11.mkv` 这类没有作品标题的弱文件名不会被伪造为冲突证据。
- 保持 `观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`，一旦当前真实缺口被覆盖就停止后续来源。Magnet/ED2K 继续走光鸭原生 `cloudcollection`，不引入 MoviePilot 下载器。

## 维护约束与代码职责

当前插件采用**单文件运行时**：`plugins.v3/guangyatransferassistant/` 目录中只允许 `__init__.py` 一个 Python 运行时代码文件。测试仍保留在 `tests/v3/guangyatransferassistant/`，README、图片、`plugin.json` 等非 Python 资源可正常保留。CI 会在插件目录重新出现其它 `*.py` 时直接失败。

单文件不等于无结构。后续维护统一在 `__init__.py` 内按职责区组织：订阅同步与固定分流、Telegram/GYING 资源发现、统一候选模型、媒体/年份/季集门禁、四类资源执行、真实落盘确认、MP 优先命名、通知与状态页。禁止继续新增 `*_vxxxx.py`、`*_final.py`、`*_verified.py` 等运行时补丁文件。

统一业务主链固定为：

```text
MoviePilot 订阅
→ Telegram / GYING 资源发现
→ MoviePilot 媒体身份 + 权威缺集匹配
→ 来源优先级：迅雷秒传 > 光鸭分享直转 > Magnet > ED2K
→ 真实目标目录落盘确认
→ MoviePilot 识别结果优先重命名
→ 成功通知
```

四种资源执行方式固定为：

- 迅雷分享：解析真实分享文件 → 生成 JSON 秒传数据 → 只导入当前权威缺集 → 光鸭秒传。
- 光鸭分享：调用光鸭原生分享恢复接口，文件级增量转存。
- Magnet：调用光鸭原生 `cloudcollection` 云添加。
- ED2K：调用光鸭原生 `cloudcollection` 云添加。
- 不接 MoviePilot 普通下载器，不接 qBittorrent、Transmission、Aria2，也不做本地整文件下载再上传兜底。

“成功”不以 API 返回 success 或 task status=completed 为准。光鸭分享必须通过目标文件可见性与大小确认；Magnet/ED2K 必须通过提交前快照与提交后目标目录新 fileId 回读；迅雷秒传必须确认新 fileId、最终文件名和大小一致。预先存在的同名文件不能归因成当前任务成功。

最终文件名以 MoviePilot 识别身份为最高优先级。电视剧采用 `剧名 - SxxExx - 技术参数.ext`；电影采用 `片名 (年份) - 技术参数.ext`。原资源中的分辨率、WEB-DL/BluRay/REMUX、H264/H265/HEVC/AV1、HDR/DV、音轨及发布组等有效技术信息尽量保留，但来源标题、错误年份、错误季集号不能覆盖 MoviePilot 身份。

所有结构或业务修改必须继续通过完整 GuangYa contract suite。当前单文件迁移完成后，历史模块源码仅以内存 bundle 兼容旧 MRO/合同测试，后续维护逐步把这些历史内部边界继续收敛到清晰职责方法，但不再恢复多文件运行时结构。

