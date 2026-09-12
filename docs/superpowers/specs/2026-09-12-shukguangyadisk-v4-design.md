# 光鸭云盘助手 V4 重建设计

## 目标

在保持 `plugins.v3/shukguangyadisk` 用户可见能力的前提下，重写 Python 运行时：以 MoviePilot V3 当前 `v3` 分支公开/稳定接口为唯一宿主契约，最终仅保留一个直接可读的 `__init__.py`，彻底移除 `_BUNDLED_SOURCES`、自定义 Finder/Loader、虚拟子模块和按版本叠加的 monkey patch。

## 全局约束

- Python 运行时代码仅存在于 `plugins.v3/shukguangyadisk/__init__.py`。
- `dist/`、图标、`plugin.json`、前端构建文件可继续保留，它们不属于 Python 运行时拆分。
- 新代码优先使用 MoviePilot V3 稳定插件门面：`app.sdk.logging`、`app.sdk.events`、`app.sdk.services`、`app.sdk.config`、`app.sdk.media`；只有 SDK 未暴露且业务确实需要时才依赖 `app.application.*` / `app.chain.*`。
- 不把 `app.log`、`app.core.event`、`app.core.config`、`app.helper.storage` 当作 V3 新代码主入口。
- 不修改、不清理宿主中无法证明属于本插件的 MoviePilot 全局整理队列任务。
- 不打印 access token、refresh token 或可恢复凭证片段；日志仅记录状态、请求阶段和脱敏设备标识。
- 自动整理必须使用 MoviePilot 自己的识别、分类、目录、命名、预览、整理历史与执行能力；插件只负责光鸭存储桥接、弱命名上下文、任务状态和远端终态确认。

## 运行时结构

单文件内部按职责顺序组织：

1. 常量、数据模型与小型纯函数。
2. `GuangYaClient`：认证、请求、Token 刷新、网络错误分类。
3. `GuangYaApi`：路径解析、目录分页、文件操作、上传下载、远端终态确认。
4. MoviePilot Storage Adapter：`get_module()`、StorageOperSelection、路径/文件模型转换。
5. WebDAV 与 `/stream`。
6. `ResourceStore`：自动整理唯一持久任务事实源。
7. `Scanner`：只发现新资源/变化，不执行整理。
8. `StabilityDetector`：`fileid + size + modify_time` 指纹与稳定期。
9. `MoviePilotContextBuilder`：调用 V3 `DirectoryHelper`、`MetaInfo`、`FormatParser`、`EpisodeFormat` 等真实接口建立上下文。
10. `OrganizerExecutor`：history gate、preview、安全校验、`TransferChain` 执行与光鸭终态确认。
11. `OrganizerCoordinator`：只选择 READY 项；WAITING/STABILIZING/RETRY_WAIT 不能阻塞后续 READY 项。
12. `MonitorService`：周期扫描、唤醒 coordinator、生命周期管理。
13. `ShukGuangYaDisk`：MoviePilot 插件入口、配置、API 与服务生命周期。

## 自动整理状态机

唯一状态集合：

`DISCOVERED -> STABILIZING -> READY -> RUNNING -> VERIFYING -> COMPLETED`

可恢复错误：`RUNNING/VERIFYING -> RETRY_WAIT -> READY`。

需要人工处理或确定性冲突：`-> BLOCKED`。

任务记录至少包含：`resource_id`、`path`、成员文件、`state`、`first_seen`、`stable_since`、`attempts`、`next_run`、`lease_owner`、`lease_until`、`last_error`。

不得再维护会与持久状态竞争的 `isolated_queue`、`pending_keys`、`known_resource`、`worker_owner`、`handoff` 等第二套控制状态。

## 公平调度规则

同一轮 coordinator 必须跳过暂不可执行项继续寻找 READY 项。例如：

- A = STABILIZING
- B = READY
- C = READY

本轮必须选 B，不得因为 A 位于队头而结束。

剧集目录同理：E03 READY、E04 STABILIZING 时，E03 必须立即整理；只有全部相关成员都满足目录批处理前提时才允许整目录执行。

## MoviePilot V3 接口基线

当前 V3 已核实存在并可作为实现依据：

- `app.sdk.logging.logger`
- `app.sdk.events.Event/eventmanager`
- `app.sdk.services.StorageHelper`
- `app.runtime.settings.get_runtime_setting`
- `app.runtime.config.global_vars`
- `app.application.directory.DirectoryHelper`
- `app.application.formatting.FormatParser`
- `app.application.history` 的 history gate/repository 接口
- `app.domain.metainfo.MetaInfo`
- `app.domain.meta.metabase.MetaBase`
- `app.schemas.workflow.FileItem`
- `app.schemas.transfer.EpisodeFormat`
- `app.monitor.dispatcher.TransferDispatcher`
- `app.application.scheduling.update_plugin_job`

是否使用某个存在的类由新架构职责决定，而不是因为“可能不存在”而猜路径。例如 V4 默认不复用 `TransferDispatcher`，原因是避免第二套宿主调度状态，不是因为类不存在。

## 存储安全语义

以下历史能力保留其业务语义，但改为 `GuangYaApi` 直接实现而非 patch：

- 目录完整分页与严格路径解析。
- API 失败与真实空目录严格区分。
- rename 后远端可见性确认。
- move 后目标 `fileId/size/name` 终态确认。
- move 不确定失败时禁止误删源文件，并执行安全恢复。
- 网络/DNS 临时错误进入可恢复状态，不标记完成。

## 热更新语义

`ResourceStore` 是任务事实源，执行器最多单并发。热更新时正在 RUNNING 的旧实例任务允许自然结束；租约到期后新实例可恢复未完成任务。不得通过抢占全局 queue、强制 stop_transfer 或清理未知宿主任务完成交接。

## UI 与兼容

保留现有 `dist/` 联邦 UI 路径和已有配置字段/API 路径，除非字段本身属于已删除的旧调度内部实现。配置迁移仅迁移用户有效配置和必要的持久整理状态，不迁移 monkey-patch 运行态。

## 测试门禁

至少覆盖：

1. 真实 MoviePilot V3 源码环境可 import、实例化插件，并调用 `init_plugin`/`get_api`。
2. `__init__.py` 不包含 `_BUNDLED_SOURCES`、自定义 MetaPathFinder/Loader 或 `install_*_vNNN` 补丁链。
3. 队头 STABILIZING、第二项 READY 时同一 coordinator pass 执行第二项。
4. Season 中已完成 + READY + 上传中成员时只执行 READY 成员。
5. A 完成后立即调度 B，不等待 heartbeat。
6. 光鸭 API 临时失败保留任务且不误报完成。
7. move API 返回成功但目标不存在时不得 COMPLETED。
8. MoviePilot preview 两源映射同一目标时执行前 BLOCKED。
9. 宿主已有 waiting queue 时插件不删除未知任务。
10. 完成资源被再次扫描不会重复执行。
11. 首次发现但远端修改时间已足够久的文件不人为再等待完整稳定期。
12. 日志不出现 access/refresh token 内容或片段。

## 发布规则

V4 重构仅在独立分支开发；在真实 MoviePilot V3 import、行为测试、基础存储测试和测试目录端到端整理通过前，不更新 `main`、不发布市场版本、不迁移生产监控。