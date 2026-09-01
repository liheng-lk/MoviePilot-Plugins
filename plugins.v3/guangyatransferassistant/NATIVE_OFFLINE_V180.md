# v1.8.0 原生云添加实现说明

## 数据流

1. 来源进入：手动 API / 观影接入 -> Magnet/ED2K 规范化并与 MoviePilot `subscribe_id` 绑定。
2. 固定分流：绑定后立即加入光鸭固定路线，MoviePilot 原生搜索、RSS 与最终下载提交仍由现有门禁阻断。
3. 目标目录：复用 `ShukGuangYaDisk._guangya_api.get_folder()` 创建/定位光鸭目标目录并取得 `parentId`。
4. 解析：`POST /cloudcollection/v1/resolve_res`。
5. 文件选择：默认只保留视频/字幕；电视剧有明确缺集时优先缺集文件。
6. 提交：`POST /cloudcollection/v1/create_task`，持久化 `taskId`。
7. 恢复：只要存在 `taskId` 就只执行 `list_task` / `retry_task`，重启或旧状态异常都不会再次 `create_task`。
8. 完成：`status=2` 后记录 `fileId`、100% 进度，并触发 MoviePilot 媒体库进度同步。
9. 失败：`status=5` 才按光鸭明确失败语义进入原生重试；单纯轮询网络故障保留 `taskId` 和 waiting 状态。

## 不使用的组件

Magnet/ED2K 云添加链路不调用 MoviePilot `DownloadChain`、下载器服务、qBittorrent、Transmission、Aria2，也不需要 ED2K HTTP Bridge。

## 状态值

- `new` / `retry`：尚需提交或请求光鸭原生重试；
- `dispatching` / `submitted` / `queued` / `waiting`：已有或即将取得服务端任务，按 taskId 轮询；
- `completed`：光鸭状态 2；
- `failed`：光鸭状态 5 且达到自动重试上限，或提交阶段连续失败达到上限。

## 对外 API

- `GET /sources`
- `POST /source/add`
- `POST /source/delete`
- `POST /source/dispatch`
- `POST /source/retry`
- `POST /offline/refresh`
- `POST /viewing/ingest`

所有接口继续经过插件现有 Bearer 会话鉴权包装。`/sources` 不返回原始 Magnet URI，以免 tracker 参数中可能存在的私有信息出现在状态接口。
