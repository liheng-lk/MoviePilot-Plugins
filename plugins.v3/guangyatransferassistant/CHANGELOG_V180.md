# v1.8.0

- 新增 Magnet / ED2K 订阅来源。
- Magnet / ED2K 统一改用光鸭云盘原生 `cloudcollection` 云添加，不经过 MoviePilot 下载器。
- 新增 `resolve_res -> create_task -> list_task -> retry_task` 可恢复任务状态机。
- 保存光鸭 `taskId`、状态、进度、`fileId`，支持进程重启后继续轮询。
- 光鸭解析出种子文件列表时支持视频/字幕筛选，并按 MoviePilot 缺集优先选择电视剧文件。
- 新增 MoviePilot 观影订阅来源入口 `/viewing/ingest`。
- 新增多来源状态控制台、后台刷新、人工重试和来源管理 API。
- 修复 queued 任务被当成待提交任务而可能重复创建云添加的问题。
- 增加 taskId 单飞保护：有服务端 taskId 时不再重新 `create_task`。
- 轮询临时网络异常不消耗提交重试次数、不误判既有云添加任务永久失败。
- `/sources` 对 Magnet 原始 tracker 参数做脱敏，仅展示稳定 BTIH 预览。
- 保留原有搜索、RSS、最终下载三层固定分流门禁和 Telegram 光鸭分享转存能力。
