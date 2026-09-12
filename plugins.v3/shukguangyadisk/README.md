# 光鸭云盘助手 3.9.8

MoviePilot V3 光鸭云盘存储与自动整理插件，Python 运行时保持唯一 `__init__.py`。

## 3.9.8 自动整理调度公平性修复

本版针对实机日志中“持久队列已有多个资源，但一个 `member_wait/stabilizing` 项挡住后续资源”的问题：

- loose 泛化目录（如“剧集”“电影”散放目录）不再固定只检查 `primary[:1]`；会跳过 completed、blocked、ignored、stabilizing、history_wait、retry_wait、inflight 等成员，寻找第一个真正 ready 的成员。
- 同一 heartbeat 中，某个资源只是 `member_wait/resource_wait/state_changed` 时，会把该项 `next_due` 后移并继续尝试其它已到期资源；仍然最多只提交一个真实 Worker，不改变单任务流水。
- 监控日志把“队列新增”和“已有队列刷新”拆开显示，避免资源变化已被刷新但日志仍显示“新增/刷新=0”的误解。
- MoviePilot 原生识别、分类、命名、移动、远端终态确认和失败保护逻辑不变。

## 3.9.7 WebDAV PUT 修复重点

本版修复单文件运行时中 WebDAV 上传成功后的确定性运行错误，不改变自动整理与 MoviePilot 主链：

- `PUT` 上传前记录目标文件是否已经存在，成功后新建资源返回 HTTP 201，覆盖已有资源返回 HTTP 204。
- 修复上传完成分支引用未定义 `item` 导致的 `NameError`，避免“远端已上传成功但 WebDAV 客户端收到 500/断开”的假失败。
- 新增单文件内嵌 `webdav_provider` 合同测试，禁止该未定义变量回归。
- MoviePilot V3 SDK、自动整理、识别、重命名、move/copy 及远端终态确认逻辑保持不变。

## 3.9.6 V3 SDK 迁移重点

本版不改变光鸭存储协议和 MoviePilot 整理主链，重点把插件与宿主的边界收敛到 MoviePilot V3 官方稳定接口：

- 日志、配置、事件、存储服务、媒体模型和调度刷新分别切换到 `app.sdk.logging/config/events/services/media/scheduler`。
- 分类一致性校验停止直接调用旧 TMDB `CategoryHelper`，改用 `app.sdk.classification.classify_media()`，始终跟随 MoviePilot 当前活动分类策略。
- 旧全局整理队列迁移仍保留 `app.db.transferpending_oper`：这是 MoviePilot V3 为旧无 Session ABI 保留的兼容门面，仅用于清理历史 pending，不进入当前整理热路径。
- Python 运行时继续保持唯一 `__init__.py`，现有识别、命名、move/copy/rename 远端终态确认和监控状态机保持不变。
- 新增 SDK 合同测试，禁止后续重新引入 `app.log`、`app.core.*`、`app.helper.storage`、旧 TMDB 分类门面等兼容路径。

## 3.9.5 修复重点

本版继续收口单文件运行态，不改 MoviePilot 识别、分类、命名、移动与远端确认主链：

- 修复插件已发布 3.9.4，但 `__init__.py` 头部、运行状态和 Federation 注释仍残留 3.9.2 的版本漂移。
- 监控状态中的 `runtime_version` 改为动态读取当前 `plugin_version`，以后升级不再因忘记同步硬编码而误判实际加载版本。
- 新增单文件运行诊断：内嵌模块总数、当前已加载虚拟模块数、当前 Finder 数量以及热更新围栏是否正常。
- 状态页直接展示运行时版本与 Finder 健康状态，方便实机判断 MoviePilot 是否仍挂着旧实例。
- 增加合同测试，禁止运行态版本再次硬编码回旧版本。

## 3.9.4 修复重点

针对“监控能发现、持久队列有任务，但页面只看到全量扫描而不开始整理”的实机表现：

- 人工全量/强校验每完成一页后立即调用持久资源队列调度，不再只扫描不执行。
- 自动 heartbeat 与人工扫描只要队列非空但没有提交 Worker，就记录明确的 `handoff / worker_busy / queue_wait / read_error` 原因。
- `queue_wait` 显示距离最早 `next_due` 的秒数；`handoff` 显示旧 owner 当前任务和 Worker 存活状态。
- 调度等待日志 30 秒节流，避免刷屏；状态接口同步保存最后调度原因、时间、等待秒数和当前任务。
- MoviePilot 原生识别、分类、命名、移动与最终远端确认逻辑保持不变。

## 3.9.3 修复重点

这版针对实机日志中“监控已发现、持久队列有任务，但旧实例 handoff 后 Worker 不继续整理”的问题做定点修复：

- **Worker 热更新交接**：不再拿着进程 owner 锁等待旧 Worker 退出。旧 Worker 的 finally 可以正常释放 owner，新实例会在同一轮立即接管，不再卡到下一次 heartbeat。
- **旧任务迁移幂等**：v3.6.2 遗留全局队列清理改成进程级锁和共享 once/recheck，同一 MoviePilot 进程的多个插件实例不会重复执行“清理旧光鸭全局任务”。
- **诊断增强**：Worker 状态增加旧 owner 的运行路径和 handoff 标记，能直接区分“真有任务收尾”和“只剩交接壳”。
- **持久资源队列保持不变**：全量扫描显示“资源>0、入待整理=0”时，如果资源已存在于持久队列属于正常去重；真正执行仍由单 Worker 串行消费。

## 3.9.2 修复重点

本版本针对实机出现的“二维码无法登录、自动整理不监控、旧历史持续刷日志”做运行态恢复：

- **二维码登录**：设备码与 token 接口失败不再吞成 `None` 或伪装成一直等待；保留上游错误信息，并用网页认证头补重试一次。二维码链路不可用时页面会明确提示，并可切换短信登录。
- **自动监控**：光鸭自定义 `/config` 和登录接口此前绕过 MoviePilot 原生配置命令，可能导致插件从未启用切到启用后 scheduler 服务没有重新注册。3.9.2 登录成功/保存配置后主动执行 MoviePilot `update_plugin_job`，并保留 5 秒启动自检及周期 heartbeat。
- **残留历史**：只接收“当前光鸭存储 + 当前监控根目录”产生的 MoviePilot 终态事件。115、本地、整理目标 STRM 等全局历史不会再被打印成光鸭整理历史；升级时一次性清理旧污染投影计数。
- **已搬空目录**：远端确认目录已经不存在时返回空直属成员并回收状态；资源队列识别 `primary=0` 后立即终态收口，不再持续复核不存在的旧文件。
- **诊断**：状态接口增加 heartbeat 最近时间、监控开关、存储就绪状态和停止原因，前端直接显示心跳状态。

## 运行原则

- 继续使用 MoviePilot 原生识别、分类、目标目录、命名与整理历史。
- 增量目录观察负责发现，持久资源队列负责排队，单 Worker 串行整理。
- Worker 忙时发现器仍继续工作，全量巡检独立补漏。
- move/copy/rename 只有远端真实终态确认后才返回成功。
- 网络/API 临时错误不伪装成目录为空。
- 无额外 Python 依赖，最低 MoviePilot `>=3.0.0`。

V2 版本仍保留在 `plugins.v2/shukguangyadisk`。
