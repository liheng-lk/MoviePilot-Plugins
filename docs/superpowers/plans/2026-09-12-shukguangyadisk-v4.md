# 光鸭云盘助手 V4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `plugins.v3/shukguangyadisk` 重建为基于 MoviePilot V3 真实接口的可读单文件插件，并恢复安全可靠的存储、WebDAV 和自动整理闭环。

**Architecture:** 一个直接源码 `__init__.py` 内部按 Client/API/Storage/ResourceStore/Scanner/Organizer/Monitor/Plugin 分区；`ResourceStore` 是自动整理唯一任务事实源，Coordinator 只挑 READY 项，MoviePilot 负责媒体识别、分类、命名和整理执行。历史 58 模块仅作为行为参考，不进入新运行时。

**Tech Stack:** Python 3、MoviePilot V3、FastAPI、requests、pytest/unittest、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-09-12-shukguangyadisk-v4-design.md`

## Global Constraints

- Python 运行时代码仅存在于 `plugins.v3/shukguangyadisk/__init__.py`。
- 使用 MoviePilot V3 当前 `v3` 分支为宿主合同。
- 禁止 `_BUNDLED_SOURCES`、自定义 Finder/Loader 和版本化 monkey-patch installer。
- 不删除无法证明归属本插件的 MoviePilot 全局队列任务。
- 不记录 access/refresh token 或可恢复凭证片段。
- 保留 `dist/` 联邦 UI 与现有用户配置/API 兼容面。

---

### Task 1: 建立 V4 架构与 MoviePilot V3 合同门禁

**Files:**
- Create: `tests/v3/shukguangyadisk/test_v4_rebuild_contract.py`
- Create: `.github/workflows/shukguangyadisk-v4.yml`
- Modify later: `plugins.v3/shukguangyadisk/__init__.py`

**Interfaces:**
- Consumes: MoviePilot V3 `app.sdk.*`、`app.application.*` 真实模块。
- Produces: 对最终单文件、合法 import 和公开插件类的硬性测试门禁。

- [ ] **Step 1: 写失败测试**：读取当前 `__init__.py`，断言不存在 `_BUNDLED_SOURCES` / `MetaPathFinder` / 版本 installer，并要求存在 V4 核心类型名。
- [ ] **Step 2: 在 CI 中运行测试并确认当前 3.9.x 明确失败**。
- [ ] **Step 3: 添加 MoviePilot V3 checkout/import smoke 环境**，真实加载宿主源码，不使用自造 `app.*` stub 证明兼容。
- [ ] **Step 4: 保持测试为红，进入 Task 2。**

### Task 2: 重建 GuangYaClient + GuangYaApi 基础层

**Files:**
- Modify: `plugins.v3/shukguangyadisk/__init__.py`
- Test: `tests/v3/shukguangyadisk/test_v4_storage_core.py`

**Interfaces:**
- Produces: `GuangYaClient`, `GuangYaApi`, `GuangYaRequestError`, `GuangYaTransientError`。
- `GuangYaApi.list_strict(path) -> list[FileItem]`
- `GuangYaApi.get_item(path) -> FileItem | None`
- `GuangYaApi.move_item(source, target_dir, new_name=None) -> FileItem`

- [ ] **Step 1: 写请求重试、分页、路径解析、move 终态失败测试并确认失败。**
- [ ] **Step 2: 直接实现 Client，不再继承 legacy Client；保留已验证光鸭 endpoint/header 语义。**
- [ ] **Step 3: 直接实现 API，不再继承 v1.1.2/v3.x API；分页和严格错误语义成为本体。**
- [ ] **Step 4: move/rename 后读取远端确认 `fileId/size/name`，不确认则抛可恢复/阻断异常。**
- [ ] **Step 5: 跑基础存储测试和 MoviePilot import smoke。**

### Task 3: MoviePilot Storage + 登录 + WebDAV/Stream

**Files:**
- Modify: `plugins.v3/shukguangyadisk/__init__.py`
- Test: `tests/v3/shukguangyadisk/test_v4_plugin_contract.py`

**Interfaces:**
- Produces: `ShukGuangYaDisk.get_module()`、StorageOperSelection、登录 API、`/browse`、`/stream`、`/webdav`。

- [ ] **Step 1: 写插件实例化、Storage 注册、API 路由和 token 日志泄漏测试。**
- [ ] **Step 2: 用 `app.sdk.logging/events/services` 实现插件基础生命周期。**
- [ ] **Step 3: 接入扫码/SMS、浏览、上传下载、WebDAV 与流式 Range。**
- [ ] **Step 4: 保留已有 Vue `dist/assets` render mode。**
- [ ] **Step 5: 跑真实 MoviePilot V3 import + init_plugin + get_api smoke。**

### Task 4: ResourceStore + StabilityDetector

**Files:**
- Modify: `plugins.v3/shukguangyadisk/__init__.py`
- Test: `tests/v3/shukguangyadisk/test_v4_resource_store.py`

**Interfaces:**
- Produces: `ResourceState`, `ResourceTask`, `ResourceStore`, `StabilityDetector`。
- `ResourceStore.next_ready(now) -> ResourceTask | None`
- `StabilityDetector.observe(task, members, now) -> ResourceState`

- [ ] **Step 1: 写 STABILIZING 队头不阻塞第二个 READY 的失败测试。**
- [ ] **Step 2: 写旧远端文件首次发现即可 READY 的失败测试。**
- [ ] **Step 3: 实现单一持久状态模型和 fingerprint 稳定判断。**
- [ ] **Step 4: 写重复扫描幂等测试并实现。**

### Task 5: MoviePilotContextBuilder + OrganizerExecutor

**Files:**
- Modify: `plugins.v3/shukguangyadisk/__init__.py`
- Test: `tests/v3/shukguangyadisk/test_v4_organizer.py`

**Interfaces:**
- Consumes: `DirectoryHelper`, `FormatParser`, `MetaInfo`, `EpisodeFormat`, `TransferChain`, `app.application.history`。
- Produces: `MoviePilotContextBuilder`, `OrganizerExecutor`。

- [ ] **Step 1: 写 history gate、preview 冲突、执行失败、远端未确认的失败测试。**
- [ ] **Step 2: 构建最小高置信上下文，不重实现 MoviePilot 分类/命名。**
- [ ] **Step 3: preview 后校验同目标冲突和无目标，再同步执行 transfer。**
- [ ] **Step 4: 只有 MoviePilot 成功且光鸭目标确认后标记 COMPLETED。**

### Task 6: Scanner + Coordinator + MonitorService

**Files:**
- Modify: `plugins.v3/shukguangyadisk/__init__.py`
- Test: `tests/v3/shukguangyadisk/test_v4_monitor.py`

**Interfaces:**
- Produces: `Scanner`, `OrganizerCoordinator`, `MonitorService`。

- [ ] **Step 1: 写 Season 中 READY E03 + STABILIZING E04 仍执行 E03 的失败测试。**
- [ ] **Step 2: 写 A 完成后 B 立即被 coordinator 领取的失败测试。**
- [ ] **Step 3: 实现 Scanner 只负责发现；Coordinator 跳过不可运行项；单执行器 callback 立即继续调度。**
- [ ] **Step 4: heartbeat 仅用于扫描与自愈，不作为任务吞吐驱动。**

### Task 7: 配置/API/前端兼容与状态迁移

**Files:**
- Modify: `plugins.v3/shukguangyadisk/__init__.py`
- Modify as needed: `plugins.v3/shukguangyadisk/plugin.json`
- Test: `tests/v3/shukguangyadisk/test_v4_compat.py`

**Interfaces:**
- 保持现有 `/config`、登录、browse、webdav、organize monitor 相关 API 的用户可见兼容面。

- [ ] **Step 1: 写旧配置字段读取/保存测试。**
- [ ] **Step 2: 迁移有效用户配置和必要整理记录，不迁移旧 Worker owner/pending queue。**
- [ ] **Step 3: 保持前端需要的状态字段，废弃字段只做只读兼容投影。**

### Task 8: 真实宿主与发布前验证

**Files:**
- Modify: `.github/workflows/shukguangyadisk-v4.yml`
- Modify: `README.md` / `ARCHITECTURE.md` after behavior stabilizes

**Interfaces:**
- Produces: 可用于非生产目录实机测试的 V4 candidate。

- [ ] **Step 1: CI checkout MoviePilot V3，运行 import/实例化/init_plugin/get_api。**
- [ ] **Step 2: 运行全部 V4 行为测试和现有光鸭存储测试。**
- [ ] **Step 3: 验证代码无 bundle/installer/token 日志。**
- [ ] **Step 4: 只在测试目录执行真实登录、浏览、上传下载、单文件整理、剧集增量整理。**
- [ ] **Step 5: 通过后再讨论版本号、市场元数据和合并；重构分支阶段不直接发布。**
