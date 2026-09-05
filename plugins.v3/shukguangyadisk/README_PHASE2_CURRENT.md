# 当前整理核心重构状态

- v3.7.0：建立唯一 `organizer_policy.py` 文件处置表。
- v3.7.1：冲突、Preview 缺员补救、旧 preview retry 迁入 Execution 显式调用。
- v3.7.2：loss guard folder 终态核对与 empty-folder 收口迁入 Execution fallback；对应两个 QueueRecovery runtime installer 退出。

后续继续优先迁移 recognition/preview 层；storage/network/Move/durable/pending 基础设施暂不拆。
