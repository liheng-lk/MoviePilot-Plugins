# v3.7.2 Phase 2 boundary

本阶段只做整理执行链收口，不新增媒体业务规则。

## 已退出运行时 monkey patch 的能力

- `install_loss_guard_v349()`
- `install_empty_folder_guard_v3410()`

`organizer_loss_guard_v349.py` 只保留 MoviePilot Preview/plan/terminal-defer helper；
`organizer_empty_folder_guard_v3410.py` 只保留源目录实时事实 helper。

## 最终显式调用关系

```text
Execution._execute_isolated_transfer
  -> _execute_conflict_aware
       -> _live_primary_media_state
       -> MoviePilot preview
       -> _audit_preview
       -> existing-target organizer_policy
       -> MoviePilot real transfer

Execution._fallback_terminal_state
  -> empty/missing terminal marker: stop
  -> folder success: _defer_unconfirmed_members
       only MoviePilot per-file terminal/history may close members
  -> ordinary failure: existing durable/policy fallback chain
```

## 不变量

- v3.7.0 `organizer_policy.py` 仍是唯一文件处置表。
- 未识别且源存在：原地保留。
- 精确字节大小一致的既有目标：最终复核后删除重复源。
- 大小不同：MoviePilot 版本化并存。
- 大小/网络/远端事实未知：fail closed，不删除。
- v3.6.20 storage + monitored path 终态隔离不变。
- v3.6.11/v3.6.21 durable admission、pending、公平调度、分页、Move 保护不变。
- 光鸭认证/API/Storage 与 MoviePilot 识别/分类/普通命名不变。
