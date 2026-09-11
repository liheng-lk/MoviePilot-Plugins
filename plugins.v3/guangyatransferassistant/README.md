# 光鸭转存助手

MoviePilot V3 固定转存插件。插件接管指定订阅后，以 MoviePilot/媒体库真实缺口为事实基础，按固定优先级补资源：

`观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`

Magnet/ED2K 始终使用光鸭原生 cloudcollection，不经过 MoviePilot 本地下载器。

> 当前版本：**2.0.13 / r97 Controlled Real-World Beta**  
> 运行要求：MoviePilot V3，且已安装并登录同仓库的 **光鸭云盘助手 ShukGuangYaDisk**。

## 先看这里

如果你是：

- **普通使用者**：先看“安装与使用”；
- **排查转存问题**：先看“运行链路”和状态页的“光鸭转存流程”；
- **准备 Fork / 二开**：先读 [ARCHITECTURE.md](ARCHITECTURE.md) 和 [DEVELOPMENT.md](DEVELOPMENT.md)；
- **准备提交 PR**：读仓库根目录 [CONTRIBUTING.md](../../CONTRIBUTING.md)；
- **查看版本历史**：读 [CHANGELOG.md](CHANGELOG.md)。

## 安装与使用

1. 安装并登录 **光鸭云盘助手 ShukGuangYaDisk**。
2. 安装本插件并打开配置页。
3. 选择需要由光鸭固定接管的 MoviePilot 订阅。
4. 配置频道 / 观影 / 迅雷相关参数。
5. 保存配置后，优先在少量订阅上人工验证，再扩大接管范围。

建议首次使用只选 5~10 个订阅，确认不存在错媒体、错季、重复任务后再扩大。

## 运行链路

固定接管订阅的主流程统一为：

```text
MoviePilot 订阅
  ↓
媒体库 / Emby 实际缺口
  ↓
频道缓存 / 新消息
  ↓
候选身份与季集校验
  ↓
观影 / 迅雷 / 光鸭 / Magnet / ED2K
  ↓
实际文件级 Episode Fence
  ↓
提交转存 / 云添加
  ↓
落盘核验
  ↓
MoviePilot / Emby 同步
  ↓
重新计算真实缺口
```

两个硬规则：

1. **API success 不等于转存完成。**
2. **只有真实目标文件可见、媒体身份正确、集号正确且真实缺口归零，才允许完成订阅。**

## 三种人工操作

### 立即检查缺集

状态页“立即检查缺集”和 `/gycheck` 使用同一条人工完整链：

`强刷频道 → 消费频道 → 重算真实缺口 → 仍有缺口才进入观影完整来源链`

人工检查可以绕过自动检索冷却，但不会绕过身份、年份、Season、Episode Fence、reservation/source claim 等安全门禁。

### 复查待落盘

这是 **verify-only** 操作：

- 只检查已经提交的任务；
- 不刷新频道；
- 不访问 GYING；
- 不创建新的转存；
- 不重复提交 cloudcollection。

### 立即转存

仅适合已经确认候选、且没有 pending 转存任务的订阅。存在待落盘任务时会被门禁阻止。

## 状态与日志

状态页“光鸭转存流程”默认按 **订阅 + 本轮 run_id** 分组展示，避免并发订阅日志交叉。

主流程只展示：

`任务 → 缺口 → 频道 → 观影 → 候选 → 转存 → 核验 → 命名 → 完成`

完整技术日志仍保留在 MoviePilot 日志和 `/plugin_logs?detail=true`。

## 资源安全边界

所有来源在最终写盘前都必须重新检查真实 payload：

- 搜索卡片 / 频道标题只负责“发现”；
- 实际分享目录、文件名、年份、Season、TMDB/媒体身份负责“确认”；
- TV/动漫不可分割视频必须满足 `actual episodes ⊆ allowed missing`；
- 已入库集、在途集、其它来源已 claim 的集不能再次提交；
- managed subscription 禁止静默回落 MoviePilot 原生下载。

## 代码结构

本插件正在从历史“版本补丁叠加”逐步收口成稳定 Authority。**不要把旧的 `*_vxxxx.py` 命名方式当成新增功能模板。**

当前关键 Authority：

| 领域 | Authority |
|---|---|
| 最终插件组合 | `__init__.py` |
| 剧集真实目标 | `episode_target_v210.py` |
| 运行周期上下文 | `episode_runtime_v211.py` |
| 核心资源 / 最终文件门禁 | `core_pipeline_v11214.py` |
| 最终调度 | `dispatch_policy_final_v1125.py` |
| 人工完整链 | `manual_check_v11211.py` |
| 频道事件 / 缓存 | `channel_event_v1115.py` + `channel_reconcile_v11215.py` |
| 观影 / GYING | `gying_*.py`，具体边界见 ARCHITECTURE |
| 迅雷秒传 | `xunlei_flash_v193.py` + 完整性/可靠性门禁 |
| Magnet / ED2K | `multisource_v180.py` + `offline_safety_v180.py` |
| 状态页 | `status_ui_v191.py` |
| 控制台 | `console_control_v1116.py` / `console_ui_v1100.py` |
| 诊断 | `diagnostics_v1100.py` / `transfer_diag_v209.py` |

完整模块边界与扩展规则见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 开发和测试

最小检查：

```bash
python -m compileall -q plugins.v3/guangyatransferassistant
python tests/v3/guangyatransferassistant/run_contract_tests.py
```

提交前还应执行仓库完整 Validate Workflow。

本插件有可维护性 CI 门禁：

- 运行 Python 模块不能继续无上限增长；
- `legacy.py` 不允许继续膨胀；
- 不允许随手新增新的 `*_final_vxxxx.py` / `*_impl_vxxxx.py` / `*_hotfix_vxxxx.py` 薄壳；
- 顶层 MRO 层数不能继续增长。

需要新增模块时，应先证明现有 Authority 无法合理承载，并在同一 PR 更新架构文档。

## Fork 建议

Fork 后建议保留上游同步分支，功能开发使用短生命周期 feature branch：

```text
main                  ← 跟随上游稳定版本
feature/<topic>       ← 单一功能
fix/<topic>           ← 单一 bug
refactor/<topic>      ← 结构收口
```

不要在一个 PR 同时做“功能 + 大规模重命名 + 架构搬迁”。先确保行为不变，再做结构收口。

## 发布状态

当前 2.0.13 仍是 Controlled Real-World Beta。CI 代表代码合同通过，不等于真实光鸭账号、真实 GYING 节点和真实 MoviePilot 配置已经完成生产验证。

实机红线：错媒体 / 错季 / 已存在剧集批量重复 / managed 回落 native / 同 episode 重复创建任务 / subtitle-only 被判媒体成功 / 媒体库 I/O 风暴 / 未来集提前批量转存。
