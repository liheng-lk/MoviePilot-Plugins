# 115 网盘助手 / 115 转存助手设计

## 目标

在 MoviePilot V3 中新增两套独立插件：

- `p115disk`：115 网盘存储 Provider，负责登录、目录、文件操作、下载链接与 MoviePilot 存储合同。
- `p115transferassistant`：115 资源转存插件，首版接三类资源：**115 分享链接**、**Magnet 磁力链接** 与 **ED2K 链接**。

上层媒体识别、缺集、重复判断、任务状态与整理完成栅栏尽量复用现有 `guangyatransferassistant` 已验证语义；115 只替换执行 Provider。

## 开源依赖边界

底层依赖 `ChenyangGao/p115client`（MIT）。

`DDSRem-Dev/MoviePilot-Plugins` 的 `p115disk` / `p115strmhelper` 仅用于核对 MoviePilot 与 115 的行为和 API 语义，不复制其 GPLv3 代码。

## 资源入口

### 1. 115 分享链接

流程：

1. 解析 `share_code` / `receive_code`。
2. 拉取分享目录树，识别视频、字幕、季、集号。
3. 与 MoviePilot 当前真实缺集做交集。
4. 只选择缺失目标文件及明确关联字幕。
5. 调用 115 `share_receive` 保存到指定临时/接收目录。
6. 轮询/事件确认保存结果。
7. 进入 MoviePilot 整理。
8. 整理终态确认后才写 `COMPLETED`。

禁止：

- 已入库集重复保存。
- 同一分享被同媒体不同季重复消费。
- 无法确认季/集的整包直接全量保存。

### 2. Magnet

流程：

1. 规范化 magnet，提取 BTIH/info_hash。
2. 先检查相同 info_hash 是否已经成功、在途或失败可恢复。
3. 尽可能获取种子文件列表并做媒体识别。
4. 对电视剧把缺集映射为 BT 文件索引。
5. 优先调用支持 `wanted` 的 `clouddownload_task_add_bt`，只离线需要的文件。
6. 无法安全拆包时，不自动整包下载；进入 `needs_review`/后续重评。
7. 轮询 `clouddownload_task_list` / `clouddownload_task` 获取状态。
8. 完成后扫描目标目录，确认真实文件，再进入整理。

兜底 `clouddownload_task_add_url` 仅用于确认是单文件或允许整包的场景，不作为电视剧整包默认路径。

### 3. ED2K

流程：

1. 规范化 `ed2k://|file|name|size|hash|/`，提取文件名、大小与 ED2K hash。
2. 用 `hash + size` 作为物理资源去重键，避免仅文件名变化造成重复任务。
3. 从文件名识别 TMDB 对应媒体、季和集号。
4. 与 MoviePilot 真实缺集及 Episode Fence 做交集。
5. 只有明确命中缺集的单文件才提交 115 离线任务；无法识别的 ED2K 不自动提交。
6. 通过 115 通用离线 URL 接口创建任务，并持久化远端任务标识。
7. 轮询任务状态；完成后必须扫描目标目录确认真实文件。
8. 文件确认后进入 MoviePilot 整理，整理终态确认后才写 `COMPLETED`。

ED2K 首版按“单文件资源”处理，不做跨多个 ED2K 链接的伪整包拼接；同一剧集多个版本由质量规则和 Episode Fence 决定唯一接管者。

## 来源优先级

首版固定：

`115 Share > Magnet > ED2K`

同一媒体/同一集一旦被更高优先级来源成功占用或完成，后续来源不再重复提交。高优先级来源明确失败并释放 reservation 后，才允许下一来源接管。

## 统一任务状态

- `DISCOVERED`
- `RESOLVED`
- `RESERVED`
- `TRANSFER_PENDING`
- `TRANSFERRING`
- `TRANSFERRED`
- `ORGANIZE_PENDING`
- `ORGANIZED`
- `COMPLETED`
- `NEEDS_REVIEW`
- `FAILED_RETRYABLE`
- `FAILED_FINAL`

任务持久化至少记录：

- `source_type`: `share115 | magnet | ed2k`
- `source_key`: `share_code`、规范化 `info_hash` 或 `ed2k_hash:size`
- `subscribe_id`
- `tmdb_id`
- `media_type`
- `season`
- `target_episodes`
- `reserved_episodes`
- `completed_episodes`
- `target_cid`
- `remote_task_id/info_hash`
- `created_at/updated_at/last_checked_at`
- `error_code/error_message`

## Episode Fence

按 `tmdb_id + season + episode` 建唯一栅栏：

- 已入库：禁止新任务。
- 已转存待整理：禁止同集其它来源。
- 已 reservation：其它来源等待。
- 失败释放 reservation 后才允许后续来源接管。

电影按 `tmdb_id` 建单资源栅栏。

## 115 关键 API

底层通过 `p115client.P115Client`：

- 登录：Cookie / QR code。
- 分享解析：`share_snap`、分享遍历工具。
- 分享接收：`share_receive`。
- 磁力离线：`clouddownload_task_add_bt` / `clouddownload_task_add_url`。
- ED2K 离线：使用 115 通用离线 URL 任务接口提交规范化 ED2K。
- 任务查询：`clouddownload_task`、`clouddownload_task_list`。
- 重试：`clouddownload_task_restart`。
- 文件：list/stat/mkdir/move/rename/delete/search/download_url。

## 首版验收

### 分享链接

- 电影分享只保存主视频及明确字幕。
- TV 分享 E01-E10，本地已有 E01-E03，只保存 E04-E10。
- 分享重复触发不产生第二份任务。
- 同一物理分享不能被同剧其它季误消费。

### Magnet

- BTIH 规范化稳定，tracker 参数变化不能生成重复任务。
- 多集种子能够按缺集生成 `wanted` 索引。
- 已有集、在途集不重复离线。
- 重启 MoviePilot 后继续恢复任务状态。
- 失败任务按可恢复/不可恢复分类。

### ED2K

- `hash + size` 规范化去重稳定。
- 能从标准剧集文件名识别 SxxExx 并只提交真实缺集。
- 同集已有/在途时不再创建第二个 ED2K 任务。
- 文件名无法高置信识别时进入 `NEEDS_REVIEW`，不盲目提交。
- 任务完成后以远端真实文件确认作为进入整理的前提。

### 整理终态

- 只有 MoviePilot 目标文件真实存在/可确认后才标记完成。
- 已完成媒体不再进入周期性整理检查。
