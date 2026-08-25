# 光鸭云盘助手 V3 架构

## 设计目标

插件只解决 MoviePilot 与光鸭远程存储之间的“适配缺口”，不复制 MoviePilot 的媒体库业务规则。

自动整理固定流水线：

`远程目录发现 → 文件稳定等待 → MP 历史预检 → 媒体上下文提示 → 受控提交 → MP 原生整理 → 最终事件回执 → 状态落盘`

任何新增功能都必须先判断属于哪一层；禁止把分类、目标目录、重命名、覆盖、刮削等 MoviePilot 已有能力重新实现到插件中。

## 模块职责

- `__init__.py`：插件组合根。只负责生命周期、账号/存储 API、各能力模块组合。
- `_plugin_legacy.py`：旧版已验证能力兼容层。新功能不得继续堆入此文件。
- `storage_contract.py`：MoviePilot V3 存储协议边界。
- `guangya_client.py` / `guangya_api*.py`：光鸭远端协议与存储操作。
- `organizer.py`：基础自动整理编排器。负责设置、稳定等待、状态展示、自检 API。
- `organizer_folder_stream.py`：按监控根直接子目录完整扫描并流式提交；完整全树扫描结束后才允许 inventory reconciliation。
- `organizer_folder_history.py`：只把文件级流水聚合为目录批次视图，不参与实际整理。
- `organizer_backpressure.py`：光鸭任务对 MoviePilot 全局整理队列的唯一背压边界；限制未终态任务、维护目录优先队列、心跳补槽和卡顿熔断。
- `organizer_dispatch.py`：自动整理到 MoviePilot 的唯一实际提交边界；无上下文时走 `TransferDispatcher`，有高置信度上下文时在此调用 `TransferChain.do_transfer`。
- `organizer_state.py`：纯持久状态机，不依赖 MoviePilot 业务对象。
- `organizer_history.py`：MoviePilot 整理历史只读预检适配，只复用宿主 history gate。
- `organizer_recognition.py`：只构造高置信度媒体类型/标题/季集提示；不决定目标路径，也不承担背压策略。
- `organizer_runtime.py`：MoviePilot 事件总线桥，负责 StorageOperSelection 与最终 Transfer 事件。
- `models.py`：API 响应模型。
- `dist/`：Federation UI。UI 只展示和操作后端状态，不持有业务状态。

## 自动整理状态机

状态以“源路径 + 文件指纹”为事实键：

- `stabilizing`：已发现，等待文件稳定。
- `inflight`：已被 MoviePilot 接受，等待最终回执。
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
6. 扫描达到 inventory cap 时不能清理未出现在本轮结果中的状态。
7. 最终事件只允许更新当前监控根下的文件，避免手动整理污染自动监控状态。
8. `batch_size` 只表示一次扫描最多处理多少新增候选，绝不能再等同于 MoviePilot 队列容量。
9. 光鸭未终态任务必须受 `max_inflight` 单独限制；默认 1，配置范围 1～8。
10. 插件不得调用 MoviePilot 私有 worker 停止/重启、不得清空 MoviePilot 全局整理队列。
11. 已被 MoviePilot 接收但长期没有终态回执的任务不得由插件自行重放；未知状态优先停提交并要求确认，避免在 MP 全局队列中制造重复任务。

## 子目录流式调度

调度单位是“监控根的直接子目录”，但 MoviePilot 仍然收到文件级任务：

`完整扫描目录 A → A 内 ready 文件受背压连续提交 → 目录 B → ...`

当一个目录因 MP 槽位不足未提交完时，它进入持久 `pending_groups`。30 秒心跳只重扫这个待补槽目录，不为每释放一个槽位重新扫描整个媒体树；当前目录消化后再轮到后续目录。

只有完整全树扫描正常结束后才执行 inventory reconciliation。DNS、远端 API、inventory cap 等导致的部分扫描绝不能把未扫描目录误判成删除。

## MoviePilot 队列隔离

MoviePilot V3 的 `TransferChain` 是全局共享队列，下载器整理、手工整理和插件整理共享同一组 worker。因此插件不能用“每轮提交 100 个”来模拟自己的独立队列。

规则固定为：

- 默认 `max_inflight = 1`，防止光鸭一次灌入大量全局待整理任务。
- 读取宿主公开 `TRANSFER_THREADS` 设置；当 worker >= 2 时，实际光鸭并发自动钳制到 `min(配置上限, worker-1)`，至少为其它 MoviePilot 整理保留一个 worker 的容量。
- 当 MoviePilot 只有 1 个整理 worker 时，真正的 worker 级隔离客观上不可能实现；插件仍只允许 1 个未终态任务，并在状态/自检中标记 `isolation_limited`。若需要远程光鸭整理与其它整理真正并行，应把 MoviePilot `TRANSFER_THREADS` 配置为至少 2。
- 最老光鸭 `inflight` 超过 `stall_timeout`（默认 900 秒）未收到最终回执时，插件进入只读式熔断：停止新增光鸭任务，但不停止、不重启、不清空 MoviePilot worker/queue。
- 为避免“任务其实仍在 MoviePilot 全局队列中，但插件超时后又重复提交”，自动整理层把 `inflight` 的自动恢复租约设为极长保护值；正常恢复依赖 MoviePilot 最终事件或历史事实，长时间未知状态要求人工检查，而不是自动重放。

## 媒体识别优先级

类型证据从强到弱：

1. 文件名明确季集：`S01E27`、`1x27`、`第27集/话`。
2. MoviePilot 用户显式目录 `media_type` 配置。
3. `Season 01` / `S01` / `全N集` 等剧集目录语义。
4. `TV/电视剧/动漫` 或 `Movie/电影` 根目录语义。
5. 无可靠证据时不强行指定类型，交回 MoviePilot 原生解析。

标题提取原则：优先使用文件名季集标记前的标题；若发布目录存在明确中文本地化标题，则去掉站点前缀、`[短剧]`、`[全31集]`、字幕标签、Season、年份、分辨率和发布组尾巴后优先使用本地化标题。

例如：

`【高清剧集网发布 www.BPHDTV.com】偏爱靠近你[短剧][全31集].../Close.to.You.S01E27...mkv`

应生成 `电视剧 / 偏爱靠近你 / S01E27 / 2025` 的识别上下文，而不是把整段发布目录当成标题。

## MoviePilot 边界

插件允许调用：

- `TransferDispatcher`：普通原生整理入口与候选扩展判断。
- `TransferChain.do_transfer`：只允许由 `organizer_dispatch.py` 在需要显式类型/meta 提示时调用。
- `app.application.history`：复用 MP 自身历史查重语义。
- `DirectoryHelper`：只读取用户已配置的目录/媒体类型。
- `StorageOperSelection`：向 MP 提供光鸭源存储 operator。
- `app.runtime.settings.get_runtime_setting`：只读宿主整理 worker 数量，用于背压计算。

插件不得自行实现：

- 电影/电视剧最终分类目录；
- 目标存储选择规则；
- 文件重命名模板；
- move/copy/hardlink 等整理策略；
- overwrite 决策；
- 刮削；
- 第二套整理历史；
- MoviePilot worker 生命周期控制；
- MoviePilot 全局队列清理。

## 故障策略

- 光鸭 API 暂时故障：扫描失败并保留原状态，下轮继续。
- MP 历史端口暂时故障：进入 `retry`，指数退避。
- MP 没接收入队：进入 `retry`，避免永久 seen。
- MP 最终失败：进入 `retry`，并记录最终错误。
- MP 失败预算耗尽：进入 `blocked`，10 分钟自动重新预检；UI 可手动立即解除后重查。
- 最终事件长时间丢失：15 分钟进入提交熔断，停止新增光鸭任务；不自动清空、不自动重启、不自动重放未知任务，先检查 MoviePilot 整理历史和实际队列状态。
- 插件停用/热重载：释放插件自己的 dispatcher pending 与运行时对象，不触碰 MoviePilot 全局 TransferChain worker。

## 发布门槛

每次自动整理修改至少需要：

1. Python 语法检查；
2. V3 插件契约测试；
3. `OrganizerStateStore` 行为单测；
4. 队列隔离/背压契约测试；
5. Federation 入口/版本一致性检查；
6. JSON 索引检查；
7. 现场 smoke test：一部电影 + 一部 `SxxExx` 剧集 + 已整理历史文件 + 故意失败文件 + 至少一个普通 MoviePilot 整理任务并行验证。

CI 通过只代表代码与契约满足发布门槛，不等于真实光鸭账号和真实 MoviePilot 配置的端到端验证。
