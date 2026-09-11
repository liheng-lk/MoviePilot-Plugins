# 光鸭转存助手架构

## 1. 目标

这个插件只维护一条固定转存业务链，不允许不同来源各自形成一套订阅状态机。

核心原则：

1. MoviePilot / 媒体库事实是订阅缺口的权威基础。
2. 搜索结果只负责发现，实际 payload 才能决定是否允许写盘。
3. GuangYa / Xunlei / Magnet / ED2K 共用同一个 Episode Target 与完成判定。
4. managed subscription 不能回落 MoviePilot 原生下载。
5. 新代码优先并入既有 Authority，不再“一版一个补丁模块”。

## 2. 最终调用链

```text
宿主事件 / scheduler / 页面 / 消息命令
        ↓
dispatch_policy_final_v1125
        ↓
manual / channel / airing / recovery policy
        ↓
episode_target_v210
        ↓
candidate discovery
  ├─ channel
  ├─ GYING / viewing
  ├─ Xunlei
  ├─ GuangYa share
  └─ Magnet / ED2K
        ↓
media identity + season + episode fence
        ↓
core_pipeline_v11214
        ↓
transfer / cloudcollection submit
        ↓
receipt / remote visibility verification
        ↓
library sync
        ↓
episode_target_v210 recompute
        ↓
complete or keep missing
```

## 3. Authority Map

### 3.1 Composition

- `__init__.py`：最终插件类和 MRO 组合，只做组合、宿主事件显式绑定和顶层兼容。
- `routing_v170.py`：消息命令 / 固定接管的宿主路由基础。
- `runtime_v170.py`：MoviePilot scheduler / takeover 运行边界。
- `foundation_ops_v209.py`：共享运行上下文、transfer diagnostics、基础协调能力。

规则：`__init__.py` 不能继续变成业务实现文件。

### 3.2 Episode Truth

- `episode_target_v210.py`：唯一剧集目标计算入口。
- `episode_runtime_v211.py`：同一运行周期内的 Emby / MP snapshot 复用。
- `calendar_driven_v209.py`：日历 due / future 事实。
- `episode_fence_v1124.py`：跨来源集级终止、在途 reservation、云添加实时裁剪的单一 Fence Authority。

核心不变量：

`final_target = actual library gap ∩ current due scope - reservation - claim - pending library`

实际细节以当前实现为准，但任何来源都不得自己扩大 target。

### 3.3 Dispatch

- `dispatch_policy_final_v1125.py`：最终 dispatch authority。
- `manual_check_v11211.py`：人工完整链。
- `channel_event_v1115.py`：被动频道 push / 缓存 tick。
- `channel_reconcile_v11215.py`：频道缓存补偿、新订阅预热。
- `airing_scheduler_v1120.py`：主动追更时钟与 due 执行。\n- `airing_weekly_v1121.py`：星期门禁、周视图和频道后观影防饿死；旧 impl wrapper 已合并。

禁止在来源模块中自行创建第二套 scheduler。

### 3.4 Discovery

频道：

- `channel_sources_v11214.py`
- `channel_message_scan_v209.py`
- `channel_cursor_event_v1115.py`
- `channel_title_rename_v11226.py`

GYING：

- `gying_runtime_v193.py`
- `gying_transport_v1108.py`
- `gying_protocol_v1106.py`
- `gying_search_truth_v11223.py`
- `gying_alias_query_v11212.py`
- `gying_recall_guard_v1125.py`

普通 Provider：

- `provider_sources_v192.py`
- `provider_reliability_v1100.py`

Discovery 层只产生候选，不允许直接把“搜到”写成“已完成”。

### 3.5 Identity and Final Write Gate

- `media_identity_v1111.py`：身份工具。
- `media_identity_guard_v1111.py`：身份门禁。
- `movie_identity_v1129.py` / `movie_bilingual_identity_v11216.py`：电影精确别名与双语桥。
- `resource_gate_v1127.py`：资源重试 / reopen gate。
- `core_pipeline_v11214.py`：所有来源最终真实文件写盘 Authority。
- `resource_planner_v190.py` / `planner_safety_v190.py`：文件选择和安全规划。

任何来源在提交前都必须进入统一写盘规则，不能用搜索标题绕过实际文件证据。

### 3.6 Execution

GuangYa direct：

- legacy 已验证分享转存基础能力；
- 新业务门禁统一在 core / safety 层。

Xunlei：

- `xunlei_flash_v193.py`
- `xunlei_hardening_v193.py`
- `xunlei_integrity_v1116.py`
- `xunlei_existing_fence_v11213.py`
- `xunlei_reliability_v1100.py`

Magnet / ED2K：

- `multisource_v180.py`
- `offline_safety_v180.py`
- `source_store_v180.py`
- `source_types_v180.py`

完成与落盘：

- `receipt_completion_v1124.py`
- `resource_inbox_v209.py`

### 3.7 Observability / UI

- `status_ui_v191.py`：紧凑状态页唯一展示 Authority。
- `console_control_v1116.py`：可执行控制台动作。
- `console_ui_v1100.py`：控制台 UI。
- `diagnostics_v1100.py`：非破坏性诊断。
- `transfer_diag_v209.py`：运行 trace。
- `config_ui_v1100.py` / `config_ui_v192.py`：配置 UI。
- `channel_ui_v1101.py` / `airing_ui_v1120.py`：领域 UI。

UI 不能持有业务真相，只展示 / 调用后端状态。

## 4. 状态机

转存状态必须区分：

```text
candidate
  ↓
identity_verified
  ↓
planned
  ↓
submitted
  ↓
task_confirmed / verifying
  ↓
verified
  ↓
library_synced
  ↓
complete
```

关键语义：

- HTTP 200 ≠ 业务成功；
- 业务 accepted ≠ 文件落盘；
- 文件落盘 ≠ 媒体完成；
- Emby 观察到文件 ≠ 能反向伪造具体来源成功回执。

“复查待落盘”只能在 submitted / task_confirmed / verifying 等已有任务状态上做 verify-only。

## 5. MRO 管理规则

当前历史实现依赖 MRO，但以后按以下规则收口：

1. 新功能不得通过再加一个顶层 Mixin 解决；
2. 优先修改当前领域 Authority；
3. 只有兼容不同 MoviePilot ABI，且无法放在原模块内时，才允许临时 adapter；
4. 临时 adapter 必须写删除条件；
5. 每次重构优先减少 MRO 层，不允许无理由增长；
6. `super()` 链必须有 final-plugin E2E 覆盖，不能只测单个 mixin。

## 6. 文件命名规则

历史文件中的版本后缀是演化遗留，不是推荐风格。

新增代码优先：

```text
episode_target.py       # 如果未来做正式目录迁移
channel_runtime.py
viewing_client.py
transfer_verifier.py
```

当前尚未执行全量重命名，是为了避免一次性破坏大量 import。迁移采用“行为不变 → Authority 合并 → 最后统一命名”的顺序。

禁止继续新增：

- `*_final_vXXXX.py`
- `*_impl_vXXXX.py`
- `*_hotfix_vXXXX.py`
- `*_patch_vXXXX.py`

除非 PR 明确说明兼容窗口与删除计划。

## 7. legacy.py 规则

`legacy.py` 只保留早期已验证且仍被大量调用的兼容实现。

新功能不得继续写入 `legacy.py`。

如果必须修改：

- 优先修 bug，不新增新子系统；
- 新增可复用逻辑应放入领域 Authority；
- 若从 legacy 抽出逻辑，必须先补 contract test，再移动。

## 8. 测试分层

1. **Source contract**：静态行为与禁用路径。
2. **Focused unit**：单个状态机 / parser / gate。
3. **Cross-layer contract**：MRO 和 super 链。
4. **Final Plugin E2E**：只 fake 外部边界，不 stub 内部业务。
5. **Real-world smoke**：真实 MoviePilot + GuangYa + GYING。

只有 Final Plugin E2E 才能证明多个 Mixin 组合后仍正确。

## 9. 重构顺序

后续按以下顺序继续减复杂度：

1. 合并 thin `*_final_*` / `*_impl_*`；
2. 合并同一领域重复 wrapper；
3. 缩短顶层 MRO；
4. 从 `legacy.py` 抽离仍活跃的业务；
5. 最后才做文件统一重命名 / 子包迁移。

不允许反过来先大搬目录再修行为。
