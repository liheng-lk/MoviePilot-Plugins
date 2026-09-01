# v1.8.0 Source API

插件 API 由 MoviePilot 插件路由暴露，并继续使用现有 Bearer 会话鉴权。

## `POST /source/add`

参数：`subscribe_id`, `uri`, `label?`, `dispatch?`。

将 Magnet/ED2K 绑定到现有 MoviePilot 订阅；`dispatch=true` 时立即后台提交光鸭原生云添加。

## `GET /sources`

参数：`subscribe_id?`。返回来源状态。Magnet 不返回原始 tracker URI。

## `POST /source/dispatch`

参数：`source_id`。后台提交/查询对应来源；有 `taskId` 时只查询既有任务。

## `POST /source/retry`

参数：`source_id`。请求光鸭原生云添加任务重试。

## `POST /offline/refresh`

立即后台刷新所有可处理来源状态。

## `POST /viewing/ingest`

参数：`subscribe_id?`, `uri`, `title?`, `year?`, `label?`, `dispatch?`。

用于 MoviePilot 观影订阅来源接入。推荐明确传 `subscribe_id`；若省略，则 `title/year` 必须唯一命中现有 MoviePilot 订阅。
