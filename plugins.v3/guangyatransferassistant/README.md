# 光鸭转存助手

MoviePilot V3 专用的固定分流与多来源订阅插件。一个 MoviePilot 订阅可以同时接收：

- Telegram 镜像频道中的光鸭分享链接；
- Magnet 磁力链接；
- ED2K 文件链接；
- MoviePilot 观影入口转入的 Magnet / ED2K 来源。

## v1.8.0 核心变化

Magnet 与 ED2K **不交给 MoviePilot 下载器**。插件复用 `光鸭云盘助手 (ShukGuangYaDisk)` 的登录态和目标目录，直接调用光鸭云盘自带的 cloudcollection 云添加能力：

`resolve_res -> create_task -> list_task -> 完成/重试`

对应光鸭接口：

- `/cloudcollection/v1/resolve_res`
- `/cloudcollection/v1/create_task`
- `/cloudcollection/v1/list_task`
- `/cloudcollection/v2/retry_task`

因此不需要 qBittorrent、Transmission、Aria2，也不需要额外的 ED2K Bridge。

## 固定分流

- 未接管的订阅：完全保持 MoviePilot 原生订阅路线。
- 已接管/已绑定外部来源的订阅：MoviePilot 原生搜索、RSS 匹配与最终下载提交都由既有硬门禁阻断。
- Telegram 暂无资源、光鸭云添加等待中、网络暂时异常时，都不会静默回退到本地下载器。
- 外部来源已经取得 `taskId` 后只轮询/重试该任务，进程重启也不会重复 `create_task`。

## Magnet / ED2K

新增来源时会做规范化和稳定身份去重。Magnet 以 BTIH 为身份；ED2K 以文件哈希为身份。同一订阅重复提交同一来源会更新原记录而不是制造重复任务。

当光鸭 `resolve_res` 返回种子文件列表时，插件默认只选择视频与字幕；电视剧若 MoviePilot 已明确知道缺集，会优先选择能覆盖缺集的文件，降低整包重复云添加。

## 观影接入

插件提供：

`POST /api/v1/plugin/GuangYaTransferAssistant/viewing/ingest`

业务参数：

- `subscribe_id`：推荐，MoviePilot 订阅 ID；
- `uri`：Magnet 或 ED2K；
- `title` / `year`：没有 `subscribe_id` 时用于唯一定位现有订阅；
- `label`：可选；
- `dispatch`：是否立即提交光鸭原生云添加，默认 `true`。

观影接入采用“订阅来源扩展”模式，不创建第二套媒体状态；绑定后仍由 MoviePilot 订阅 ID、缺集状态和固定分流规则统一管理。

## 状态页

v1.8.0 将多来源控制台放到状态页顶部，展示来源总数、等待/运行、完成、失败，以及最近 Magnet/ED2K 云添加任务。高级区域继续保留固定分流健康、频道索引、未转存原因、自检、任务历史等原有诊断。

来源列表 API 不返回原始 Magnet tracker 参数，避免状态接口暴露可能存在的私有 tracker 信息。

## 默认频道

- 光鸭云盘影视热更频道：`https://tgm.li668.asia/regengguangya`
- 光鸭云盘资源分享频道：`https://tgm.li668.asia/yunpanguangya`

## 依赖

需要安装并登录同仓库的 `光鸭云盘助手 (ShukGuangYaDisk)`。本插件直接复用其运行态客户端、Token 刷新、目录创建和文件查询能力，不保存第二份光鸭登录凭据。
