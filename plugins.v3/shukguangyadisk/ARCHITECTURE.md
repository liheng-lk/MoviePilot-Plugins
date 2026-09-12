# 光鸭云盘助手 V4 架构

## 目标

V4 只以 MoviePilot V3 当前公开/稳定接口为宿主契约，不继续兼容 v3.4~v3.9 的运行时补丁结构。

Python 运行时代码物理上仍只有 `__init__.py`，但它是普通可读 Python，不再包含 JSON 虚拟模块、MetaPathFinder、动态 Loader 或 `install_xxx_vNNN()` 链。

## MoviePilot V3 边界

插件优先使用：

- `app.sdk.logging`
- `app.sdk.events`
- `app.sdk.config`
- `app.sdk.services.StorageHelper`
- `app.chain.transfer.TransferChain`
- `app.application.directory.DirectoryHelper`
- `app.application.history`
- `app.runtime.settings.get_runtime_setting`
- `app.schemas.workflow.FileItem`
- `app.schemas.transfer.EpisodeFormat`

MoviePilot 继续负责媒体识别、分类、目标目录、命名、覆盖、刮削和整理历史。插件不维护第二套媒体库业务规则。

## 单文件内部结构

```text
GuangYaClient
  ↓
GuangYaApi
  ↓
V3StorageContract
  ↓
WebDAV / Stream / Upload
  ↓
ResourceStore
  ↓
BFS Scanner
  ↓
Single Executor
  ↓
MoviePilot Preview
  ↓
MoviePilot TransferChain(background=False)
  ↓
MoviePilot History Verification
```

## 自动整理状态

V4 使用一套持久资源状态：

- `STABILIZING`：文件仍在稳定等待。
- `READY`：允许执行。
- `RUNNING`：已被当前插件实例 lease 认领。
- `RETRY`：暂时错误，达到 `next_run` 后再执行。
- `VERIFYING`：MoviePilot 同步执行已经返回成功，只等待成功历史；严禁重复 move。
- `BLOCKED`：安全预览冲突、重试预算耗尽或执行后长期无终态，需要人工检查。
- `COMPLETED`：MoviePilot 成功历史确认或源已经明确消失且不应重复提交。

只有这一套状态是真实任务队列。不存在第二套内存 backlog、MoviePilot 全局 queue 清理或 owner handoff 队列。

## 调度不变量

1. `STABILIZING` / 未到期 `RETRY` 永远不能阻塞后面的 `READY`。
2. 执行器固定 `max_workers=1`，同一时刻最多一个真实整理任务。
3. 一个任务 callback 收口后立即调用下一次 dispatch，不依赖下一次 heartbeat 提升吞吐。
4. 热更新时旧实例停止接新任务；正在运行的任务保留 lease 自然收尾。新实例只有在 lease 过期后才恢复任务，避免重复整理。
5. 插件绝不调用 MoviePilot 的 `remove_from_queue`、`TransferPendingOper.discard` 或全局 stop 来清理未知任务。
6. MoviePilot 同步执行返回成功但历史尚未可见时进入 `VERIFYING`，只做历史确认，不重复执行。
7. 安全预览要求当前源必须成功映射到目标，且多个源不能映射同一个目标。

## 扫描

Scanner 使用持久 BFS 游标，每个 heartbeat 只扫描有限数量目录。Worker 忙时 Scanner 仍继续推进，因此发现和执行完全解耦。

文件指纹：

```text
fileid | size | modify_time
```

首次发现旧文件时允许使用可信远端 `modify_time` 作为 `stable_since`，避免旧资源平白再等待完整稳定窗口；同一路径指纹发生变化时一律从当前时间重新稳定。

## Season / Episode

任务粒度默认是主媒体文件，因此：

- E03 已 READY、E04 仍 STABILIZING 时，E03 可以立即执行；
- 不再因为 Season 内一个成员等待就返回整个 `resource_wait`；
- TV 场景优先调用 MoviePilot `TransferChain.recommend_episode_format(fileitems=...)`，并把结果作为 `EpisodeFormat` 交回 MoviePilot；
- 标准 `Season 1 / S01 / 第1季` 只作为高置信 season/type 提示，不替代 MoviePilot 最终识别。

## 存储安全

V4 直接集成而不是 patch：

- 逐级完整分页路径解析；
- `GuangYaApi` 实例级 path/fileId cache；
- `list_strict`：API 失败必须抛出，禁止伪装为空目录；
- 整理后旧源路径只读检查：`any_files=False`、`list_files=[]`；
- Token 日志不打印 access/refresh token 片段。

移动事务的远端终态确认和失败回滚保护仍需要在 V4 分支继续直接并入 `GuangYaApi`，完成后才进入实机发布阶段。

## 发布门槛

V4 合并前至少通过：

1. `py_compile` / `compileall`；
2. 对真实 MoviePilot V3 源码的 import smoke；
3. READY 越过 STABILIZING 的行为测试；
4. Season “已完成 + READY + 上传中”测试；
5. A 完成后 B 立即启动测试；
6. 热更新 lease 测试；
7. MoviePilot host queue 不被插件修改测试；
8. preview 多源同目标阻断测试；
9. Token 日志敏感信息测试；
10. 测试目录真实光鸭账号端到端验证。

当前分支为 V4 alpha，不直接替换生产 v3.9.5。
