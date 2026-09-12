# 光鸭云盘助手 3.9.1

MoviePilot V3 专用光鸭云盘存储插件。

## 3.9.1 单文件运行时

本版本将插件全部 Python **运行时代码物理收敛到唯一 `__init__.py`**。账号登录、光鸭 API、存储协议、上传、WebDAV、MoviePilot 自动整理、状态机、监控、网络容错、重命名与移动终态确认均保留，不再依赖插件目录中的大量 `*_legacy.py` / `*_vxxxx.py` 运行文件。

同时修复 3.9.0 的安装注册边界：Organizer API 注册不再通过基础 `get_organizer_api()` 间接执行 `init_organizer_monitor()`，MoviePilot 安装/热更新 COMMIT 前不会因为 API 注册而启动监控或访问光鸭远端。

运行原则：

- 自动整理继续使用 MoviePilot 原生识别、分类、目标目录、命名、整理方式和历史，不在插件中复制第二套媒体规则；
- 严格单任务执行，持续增量发现与独立全量补漏并存；
- move/copy/rename 只有远端真实目标可见并完成终态确认后才返回成功；
- 网络/API 临时故障保持可恢复状态，不把读取失败伪装为空目录；
- 热更新会清理上一版本残留的虚拟子模块，避免新旧逻辑混用；
- 无额外 Python 依赖，最低 MoviePilot `>=3.0.0`；
- Vue Federation 页面继续使用 v390 页面实现，缓存版本更新为 3.9.1。

V2 版本继续维护在 `plugins.v2/shukguangyadisk`，版本保持 1.1.2。
