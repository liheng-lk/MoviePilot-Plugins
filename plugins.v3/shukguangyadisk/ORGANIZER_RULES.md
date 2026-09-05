# 光鸭云盘助手自动整理不可变规则

本文件从 v3.7.0 起是自动整理功能的行为契约。后续任何修复先修改/验证这里的规则，禁止用新的版本补丁模块绕开这些约束。

## 一条流水线

`发现 → 稳定确认 → MoviePilot 识别/预览 → organizer_policy 决策 → 执行 → 终态/简洁日志`

### 文件处理矩阵

| MoviePilot/远端事实 | 决策 | 允许的动作 |
| --- | --- | --- |
| 识别成功、目标可靠、目标不存在 | ORGANIZE | 按 MoviePilot 规划精准整理 |
| 识别失败且源确认仍存在 | LEAVE_UNRECOGNIZED | 原地保留；不移动、不删除、不改名、不 retry |
| 识别失败但源存在性未知 | RETRY_TRANSIENT | 仅退避重试，不做文件写操作 |
| 源明确不存在 | RETIRE_MISSING | 只清本地调度状态 |
| 最终目标已存在，双方字节大小已知且完全相同 | DELETE_DUPLICATE | 删除源重复文件；删除前再次核对大小/fileId |
| 最终目标已存在，双方字节大小已知且不同 | ORGANIZE_VERSION | 生成稳定版本名后二次 preview，确认唯一再整理 |
| 任一大小未知 | BLOCK_SAFETY | 不删除、不覆盖，源保持原位 |

## 不允许破坏的边界

1. 媒体身份、分类目录、普通重命名模板、目标存储、move/copy、刮削仍由 MoviePilot 决定。
2. 光鸭插件只在“安全终态”上补充：识别失败原地停放、同大小去重、不同大小多版本、远端真实性确认。
3. 删除必须有比“文件名相同”更强的证据：MoviePilot 已确认同一最终目标 + 两边精确字节大小相同 + 删除前二次远端核验。
4. 未识别文件不是失败队列任务。内容不变时只记录一次；文件指纹变化后可以重新进入识别。
5. `completed` 是短期调度缓存，不是历史数据库；真正整理历史属于 MoviePilot。光鸭 UI 只保留有限的近期流水。
6. 网络/API异常永远不能转换成“文件不存在”“未识别”或“重复”。

## 重构约束

v3.6 及更早的 `install_*_vXXXX()` 图从这里起冻结：**不得继续新增同类行为补丁**。

后续分阶段把旧能力迁入五层核心：

1. `discovery`：发现/分页/稳定性；
2. `recognition`：MoviePilot 身份与 preview；
3. `organizer_policy.py`：唯一文件决策；
4. `executor`：光鸭 move/delete/version 与真实性确认；
5. `state/reporting`：仅活动调度状态 + 有界近期日志。

每迁移一个旧 installer，必须先有等价行为测试，再删除旧安装入口；禁止“新核心 + 旧补丁同时各做一遍”。
## Phase 2 migration rule

从 v3.7.1 开始，文件处置相关能力必须由最终 MRO 中的执行核心显式调用。
`organizer_conflict_resolution_v353.py` 与 `organizer_preview_partial_v355.py` 只允许保留纯函数/纯 helper，
不得再修改 `GuangYaQueueRecoveryMixin`、`GuangYaFolderStreamMixin` 或 `GuangYaOrganizerMixin` 的类方法。
旧状态迁移可以保留兼容 helper，但必须由生命周期入口显式调用一次，禁止通过扫描 monkey patch 隐式执行。
