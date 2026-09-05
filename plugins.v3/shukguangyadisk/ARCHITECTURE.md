# 光鸭云盘助手 V3 架构

> **v3.7 重构规则**：自动整理的文件终态统一由 `organizer_policy.py` 决定，详细不可变规则见 `ORGANIZER_RULES.md`。v3.6 以前的 `install_*_vXXXX()` 行为图已冻结，不再新增版本补丁；后续只允许把已有能力逐步迁移进 discovery / recognition / policy / executor / state-reporting 五层核心。

## 设计目标

插件只解决 MoviePilot 与光鸭远程存储之间的“适配缺口”，不复制 MoviePilot 的媒体库业务规则。

v3.5.0 起自动整理固定流水线：

`发现一个资源单元 → 文件稳定等待 → MP 历史预检 → 作品目录识别 → 单文件季集解析 → MP 原生预览 → 安全校验 → MP 原生整理 → 远端终态确认 → 最终事件回执 → 再发现下一个`

任何新增功能都必须先判断属于哪一层；禁止把分类、目标目录、重命名、覆盖、刮削等 MoviePilot 已有能力重新实现到插件中。

### v3.5.0 的两个核心不变量

1. **严格单任务流水**：私有 worker 同一时刻只拥有一个资源任务，运行中不预排第二个；当前资源结束后再扫描下一个，避免“先识别几十个、再慢慢整理”的积压。
2. **作品身份与单文件集号分离**：作品身份优先来自真实作品目录；`Season 1/01 4K.mp4` 中 `Season 1` 只表示季，`01 4K.mp4` 只参与集号解析，不能因为文件名弱或错误就否定已经确认的作品目录。

## 资源单元

自动整理的最小调度对象不是固定的“一个文件”，而是一个可安全独立完成的资源单元：

- 电视剧、短剧、动漫、Season 目录：整个剧集目录是一个资源单元，MoviePilot 一次预览整组成员并检查唯一目标；
- 单作品电影目录：目录是一个资源单元，以保留正确的父目录作品身份；
- `mp/电影/华语电影` 等容器目录中散放的多部独立视频：每个主要视频分别作为资源单元，严格串行，不把整个容器目录交给 MoviePilot 批量规划。

资源单元之间绝不形成插件内部 backlog。电视剧目录内部可以包含多集，但它仍然是**一个**事务任务。

## 模块职责

- `__init__.py`：插件组合根。只负责生命周期、账号/存储 API、各能力模块组合。
- `_plugin_legacy.py`：旧版已验证能力兼容层。新功能不得继续堆入此文件。
- `storage_contract.py`：MoviePilot V3 存储协议边界。
- `guangya_client.py` / `guangya_api*.py`：光鸭远端协议与存储操作。
- `organizer.py`：自动整理编排器。负责扫描、稳定等待、状态展示、自检 API。
- `organizer_folder_stream.py` / `organizer_deep_folder_stream_v3413.py`：递归发现真实文件所在目录。
- `organizer_single_flight_v350.py`：严格单任务背压与“容器散放电影逐个处理”。
- `organizer_folder_identity_v350.py`：作品目录身份解析；不负责集号。
- `organizer_episode_name_adapter_v3411.py`：只负责 MoviePilot 未覆盖的集号位置兼容，并必须经 MP FormatParser 反向校验。
- `organizer_loss_guard_v349.py`：MoviePilot 真实整理前的源→目标唯一性预览校验。
- `guangya_rename_integrity_v3414.py`：同盘 move/copy/rename 后远端真实可见性确认。
- `organizer_state.py`：纯持久状态机，不依赖 MoviePilot 业务对象。
- `organizer_history.py`：MoviePilot 整理历史只读预检适配，只复用宿主 history gate。
- `organizer_recognition.py`：根目录散放文件等兼容路径的高置信度上下文桥；不决定目标路径。
- `organizer_runtime.py`：MoviePilot 事件总线桥，负责 StorageOperSelection 与最终 Transfer 事件。
- `models.py`：API 响应模型。
- `dist/`：Federation UI。UI 只展示和操作后端状态，不持有业务状态。

## 自动整理状态机

状态以“源路径 + 文件指纹”为事实键：

- `stabilizing`：已发现，等待文件稳定。
- `inflight`：已被当前唯一资源任务占有，等待 MoviePilot 最终回执。
- `retry`：暂时性故障，按退避时间重新尝试。
- `blocked`：MoviePilot 明确表示失败重试预算耗尽；暂停提交并定期重新预检。
- `completed`：收到 MoviePilot 最终成功事件，或 MP 历史确认同版本已成功。
- `ignored`：MoviePilot 当前扩展名规则明确不处理。

### 不变量

1. **“提交 MP”绝不等于“整理完成”**。只有最终成功事件或 MP 成功历史可以进入 `completed`。
2. 调用 MoviePilot 前必须先写 `inflight`，避免快速回执和扫描线程竞态。
3. MP 历史查询失败只能进入可重试状态，不能写 `completed/ignored`。
4. 旧版 `seen` 不能直接迁移为 `completed`，因为历史版本曾把“提交成功”误当完成。
5. 文件指纹变化必须自动重新开放处理。
6. 单任务扫描在提交当前资源后属于“有意的部分扫描”，不得用未扫描到的路径清理旧状态。
7. 最终事件只允许更新当前监控根下的文件，避免手动整理污染自动监控状态。
8. 电视剧文件夹预览中任一源文件缺失、失败、目标为空或多个源映射到同一目标时，整目录禁止真实 move。
9. 光鸭同盘移动/复制只有在 MoviePilot 目标名称真实可见并通过 fileId/大小确认后才向宿主返回成功。

## 作品识别与集号解析

作品身份与文件季集是两个独立问题。

例如：

`/花开锦绣 (2026)/Season 1/01 4K.mp4`

必须拆成：

- 作品目录：`/花开锦绣 (2026)` → 交给 MoviePilot 识别作品；
- 季目录：`Season 1` → Season 1；
- 文件：`01 4K.mp4` → 只解析 Episode 1。

因此允许出现：

- `作品识别成功 + 集号解析失败`：源文件保持原位，提示具体阻塞文件；
- 不允许：`一个弱文件名解析失败 → 整个作品身份被改成另一个电影/电视剧`。

集号证据从强到弱：`S01E27`、`1x27`、`EP27/E27`、`第27集/话`、`[27]`、`27~[4K]`、`27 4K`、`27.mp4`。弱命名必须使用整组样本证明唯一性，并经 MoviePilot `FormatParser` 对整组反向验证。

## MoviePilot 边界

插件允许调用：

- `TransferChain.do_transfer`：真实整理与 `preview=True` 预览；
- `MediaChain.recognize_by_path/recognize_by_meta`：作品目录识别；
- `TransferChain.recommend_episode_format` / `FormatParser`：集号位置推荐和验证；
- `app.application.history`：复用 MP 自身历史查重语义；
- `DirectoryHelper` / `CategoryHelper`：只读取并执行用户当前 MoviePilot 配置；
- `StorageOperSelection`：向 MP 提供光鸭源存储 operator。

插件不得自行实现：

- 电影/电视剧最终分类目录；
- 目标存储选择规则；
- 文件重命名模板；
- move/copy/hardlink 等整理策略；
- overwrite 决策；
- 刮削；
- 第二套整理历史。

## 故障策略

- 光鸭 API 暂时故障：扫描失败并保留原状态，下轮继续。
- MP 历史端口暂时故障：进入 `retry`，指数退避。
- MP 没接收当前资源：进入 `retry`，但绝不把第二个资源塞进队列补位。
- MP 预览不满足一一映射：当前整个文件夹阻止真实整理，源文件保持原位。
- MP 最终失败：进入 `retry`，并记录最终错误。
- MP 失败预算耗尽：进入 `blocked`，10 分钟自动重新预检；UI 可手动立即解除后重查。
- 最终事件丢失/进程崩溃：`inflight` 租约到期后自动恢复。
- 插件停用/热重载：只允许当前同步任务收尾，未开始任务退回持久状态；v3.5.0 正常情况下私有队列不再积压未开始任务。

## 发布门槛

每次自动整理修改至少需要：

1. Python 语法检查；
2. V3 插件契约测试；
3. `OrganizerStateStore` 行为单测；
4. Federation 入口/版本一致性检查；
5. JSON 索引检查；
6. 单任务流水合同：worker 忙时不得 admission 第二个任务；
7. 作品目录合同：Season 子目录必须使用上一级作品目录识别；
8. 现场 smoke test：散放多电影目录 + 一部电影发布目录 + 一部 `SxxExx` 剧集 + 一部 `01 4K` 弱命名剧集 + 故意冲突目标。

CI 通过只代表代码与契约满足发布门槛，不等于真实光鸭账号和真实 MoviePilot 配置的端到端验证。
