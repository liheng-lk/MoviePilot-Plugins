# 光鸭转存助手 v1.8.0 交付验收矩阵

| 场景 | 期望结果 |
|---|---|
| 绑定 Magnet | 规范化 BTIH、写入订阅来源、加入固定分流、后台调用光鸭 `resolve_res/create_task` |
| 绑定 ED2K | 校验 file/size/hash、写入订阅来源、加入固定分流、后台调用光鸭 `resolve_res/create_task` |
| 已存在 taskId | 只调用 `list_task` 或 `retry_task`，不得再次 `create_task` |
| 光鸭 status=0/1/3/4 | queued/waiting，持续轮询 |
| 光鸭 status=2 | completed，记录 fileId/100%，同步媒体库进度 |
| 光鸭 status=5 | retry；达到上限后 failed |
| 轮询临时断网 | 保留 taskId、waiting 和原 attempts，不误判永久失败 |
| MoviePilot 原生搜索/RSS | 已绑定来源的订阅继续被固定分流门禁阻断 |
| Magnet tracker 隐私 | `/sources` 不返回原始 URI，只返回 BTIH 预览 |
| 观影接入 | 复用现有 MoviePilot 订阅 ID，来源 origin=viewing，仍走光鸭原生云添加 |
| 状态页 | 顶部显示来源总数、等待/运行、完成、失败和最近云添加任务 |
| 重启恢复 | 来源和 taskId 持久化，下一轮继续查询既有光鸭任务 |

CI 必须通过仓库 `Validate MoviePilot Plugins`，其中包括 Python compileall、全仓 unittest、光鸭专用函数式契约测试和 JSON 索引校验。
