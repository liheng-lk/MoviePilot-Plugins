# 光鸭云盘助手 v3.7.1 Phase 2

本阶段只做整理执行架构收口，不增加新的媒体业务规则。

## 已移除的运行时行为 installer

- `install_conflict_resolution_v353()`
- `install_preview_partial_v355()`
- `install_preview_retry_wakeup_v356()`

对应 helper 不再改写 `GuangYaQueueRecoveryMixin`、`GuangYaFolderStreamMixin` 或 `GuangYaOrganizerMixin` 类方法。

## 当前显式执行链

```text
Execution._execute_isolated_transfer
  -> _execute_conflict_aware
  -> rescue_partial_preview_if_needed

Execution.organizer_transfer_rename
  -> apply_version_rename_event

PendingRevisit._record_terminal_transfer
  -> v3.6.20 storage/path outer scope
  -> Execution._record_terminal_transfer
  -> normal MoviePilot history/terminal chain
  -> handle_duplicate_terminal_event
```

旧 v3.5.6 preview retry 状态迁移保留为一次性 helper，由 `init_organizer_monitor()` 显式调用，不再包裹每次扫描。

## 文件策略不变

继续严格遵守 v3.7.0：未识别原地保留；同大小精确复核后去重；不同大小版本化；事实未知 fail closed；源明确消失只退休本地状态。

## 安全边界

- 115、本地和其它存储终态仍由 v3.6.20 在 Pending 外层拒绝，无法进入 duplicate cleanup。
- 不改变 MoviePilot 识别、分类、普通命名或 durable admission。
- 不改变光鸭认证、API、存储协议、分页、Move 事务保护。
