# 光鸭云盘助手 3.0.0

MoviePilot V3 专用光鸭云盘存储插件。

V3 版保留 V2 1.1.2 已实机验证的上传、登录、目录、WebDAV 和网络容错核心，同时迁移 MoviePilot V3 的插件边界：

- 使用 `plugins.v3/ + package.v3.json`，最低 MoviePilot `>=3.0.0`；
- 新增 `pyproject.toml` 依赖清单；
- 新入口使用 `app.sdk.logging`、`app.sdk.services` 等稳定 SDK；
- 配置、登录、目录浏览 JSON API 声明明确 `response_model`；
- Vue Federation 暴露层只接受 MoviePilot 注入的 API 客户端或 `MoviePilotAPI`；
- `stop_service()` 可重复释放客户端和临时登录状态；
- 保留上传 `142` 目录恢复、`145/147` 落盘确认、同名同大小幂等、90 秒确认及上传进度监控。

V2 版本继续维护在 `plugins.v2/shukguangyadisk`，版本保持 1.1.2。
