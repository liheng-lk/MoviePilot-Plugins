# 光鸭云盘助手 V3 架构

## 设计目标

插件只解决 MoviePilot 与光鸭远程存储之间的“适配缺口”，不复制 MoviePilot 的媒体库业务规则。

自动整理固定流水线：

`远程目录发现 → 文件稳定等待 → MP 历史预检 → 媒体上下文提示 → MP 原生整理 → 最终事件回执 → 状态落盘`

任何新增功能都必须先判断属于哪一层；禁止把分类、目标目录、重命名、覆盖、刮削等 MoviePilot 已有能力重新实现到插件中。

## 模块职责

- `__init__.py`：插件组合根。只负责生命周期、账号/存储 API、各能力模块组合。
- `_plugin_legacy.py`：旧版已验证能力兼容层。新功能不得继续堆入此文件。
- `storage_contract.py`：MoviePilot V3 存储协议边界。
- `guangya_client.py` / `guangya_api*.py`：光鸭远端协议与存储操作。
- `organizer.py`：自动整理编排器。负责扫描、稳定等待、批次限流、状态展示、自检 API。
- `organizer_state.py`：纯持久状态机，不依赖 MoviePilot 业务对象。
- `organizer_history.py`：MoviePilot 整理历史只读预检适配，只复用宿主 history gate。
- `organizer_recognition.py`：只构造高置信度媒体类型/标题/季集提示；不决定目标路径。
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

## 媒体识别优先级

类型证据从强到弱：

1. 文件名明确季集：`S01E27`、`1x27`、`第27集/话`。
2. MoviePilot 用户显式目录 `media_type` 配置。
3. `Season 01` / `S01` / `全N集` 等剧集目录语义。
4. `TV/电视剧/动漫` 或 `Movie/电影` 根目录语义。
5. 无可靠证据时不强行指定类型，交回 MoviePilot 原生解析。

标题提取原则：优先使用文件名季集标记前的标题；若发布目录存在明确中文本地化标题，则去掉站点前缀、`[短剧]`、`[全31集]`、字幕标签、Season、年份、分辨率和发布组尾巴后优先使用本地化标题。

例如：

`【高清剧集网发布 www.BPHDTV.com】偏爱靠近你[短剧][全31集][国语配音+中文字幕].Close.to.You.S01.2025.../Close.to.You.S01E27...mkv`

应生成 `电视剧 / 偏爱靠近你 / S01E27 / 2025` 的识别上下文，而不是把整段发布目录当成标题。

## MoviePilot 边界

插件允许调用：

- `TransferDispatcher`：普通原生整理入口与候选扩展判断。
- `TransferChain.do_transfer`：需要显式类型/meta 提示时的稳定整理入口。
- `app.application.history`：复用 MP 自身历史查重语义。
- `DirectoryHelper`：只读取用户已配置的目录/媒体类型。
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
- MP 没接收入队：进入 `retry`，避免永久 seen。
- MP 最终失败：进入 `retry`，并记录最终错误。
- MP 失败预算耗尽：进入 `blocked`，10 分钟自动重新预检；UI 可手动立即解除后重查。
- 最终事件丢失/进程崩溃：`inflight` 30 分钟租约到期后自动恢复。
- 插件停用/热重载：释放 dispatcher pending 与运行时对象，新实例通过弱引用桥接管事件。

## 发布门槛

每次自动整理修改至少需要：

1. Python 语法检查；
2. V3 插件契约测试；
3. `OrganizerStateStore` 行为单测；
4. Federation 入口/版本一致性检查；
5. JSON 索引检查；
6. 现场 smoke test：一部电影 + 一部 `SxxExx` 剧集 + 已整理历史文件 + 故意失败文件。

CI 通过只代表代码与契约满足发布门槛，不等于真实光鸭账号和真实 MoviePilot 配置的端到端验证。
