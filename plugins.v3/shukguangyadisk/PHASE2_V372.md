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

## v3.7.3 recognition / Preview continuation

- `install_episode_name_adapter_v3411()` 退出运行图；弱命名/整组集号兼容改为纯 helper。
- `install_episode_sample_bridge_v3411()` 与整个 ContextVar bridge 模块删除；folder members 直接传给 MoviePilot `recommend_episode_format`。
- `install_category_consistency_v3412()` 退出运行图；分类只由 MoviePilot `CategoryHelper` 在显式 Preview 上下文中复核。
- `organizer_loss_guard_v349._build_moviepilot_kwargs()` 明确执行：一次 MoviePilot 目录识别 → 集数适配 → 分类一致性。
- TV 约束重识别复用同一次目录识别的 `meta_info`，同一 Preview 构建过程不二次 `recognize_by_path`。
- Preview 唯一目标校验通过后，再显式执行弱命名 season/episode 终态复核；任何不一致仍 fail closed。

## 共享市场索引发布约束

`package.v3.json` 是多插件共享发布面。若 PR 验证期间 `main` 上其它插件已经升级，Shuk 发布分支必须先同步最新 `main`，并按插件条目保留各自最新对象；禁止用旧 checkout 整份覆盖市场索引。同步后必须重新执行 PR CI，正式发布仍以 main-push CI 与 Raw `main/package.v3.json` 校验为最终门禁。
