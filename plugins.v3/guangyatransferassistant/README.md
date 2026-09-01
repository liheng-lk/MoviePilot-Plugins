# 光鸭转存助手

MoviePilot V3 固定分流与多来源订阅插件。Telegram 频道、观影 GYING、Magnet/ED2K 搜索接口发现的候选都绑定同一个 MoviePilot 订阅状态，不建立第二套追剧进度。Magnet/ED2K 始终交给光鸭原生 cloudcollection，不经过 MoviePilot 下载器。

## v1.9.3：完整观影会话 + 迅雷最高优先级秒传

最终资源优先级固定为：

`观影迅雷秒传 > 光鸭直接转存 > Magnet 光鸭云添加 > ED2K 光鸭云添加`

### 1. 观影不再固定单域名

GYING 会更换内容节点，部分节点可能只是地址发布页、维护页或临时不可用。v1.9.3 建立独立节点池：

- 默认读取 `https://www.gying.page`、`https://gying.si` 等发布/换址入口；
- 支持首选节点，例如 `https://www.星际穿越.com`；
- 支持手动备用节点，每行一个；
- 自动缓存发现的节点与最近成功节点；
- 维护、换址页、阻断、搜索失败节点进入短暂冷却，自动尝试下一节点；
- 中文 IDN 与 punycode 节点都可以使用；
- 节点列表默认缓存 360 分钟，避免每次搜索都访问发布页。

配置页对应字段：`viewing_registry_urls`、`viewing_base_url`、`viewing_node_urls`、`viewing_auto_switch`、`viewing_node_cache_minutes`。

### 2. 浏览器计算验证 / PoW

观影的“正在确认你是不是机器人 / 浏览器安全验证”不是普通账号登录失败。插件保持同一个 `requests.Session` 和浏览器化请求头，当前兼容三类站点计算验证：

1. **远程 PoW**：`GET /res/pow` 取得 `N/x/t`，计算 `y=(y*y)%N` 共 `t` 次，再 `POST /res/pow` 提交 `y`；
2. **内嵌 PoW**：页面直接给出 `id/N/x/t`，完成同样的平方取模后提交 `action=verify&id=...&y=...`；
3. **旧版哈希 challenge**：按 `challenge/diff/salt` 枚举 nonce，并按原顺序提交 `nonce[]`。

验证成功后的 `browser_verified/browser_pow` 与账号登录 Cookie 属于不同状态。插件把同一节点的最新 Cookie 私下保存到 `viewing_session_state` 并在重启后复用，公开 API 不返回 Cookie、密码或 challenge 明文。

此流程只复现站点前端公开执行的计算验证，不绕过账号权限；需要账号访问的内容仍必须使用用户自己的账号密码或合法取得的 Cookie。

### 3. 观影真实接口

最终运行时使用当前 GYING 实际链路：

```text
GET  {node}/
POST {node}/user/login
GET  {node}/search?q={keyword}&type=0&mode=2
GET  {node}/res/downurl/{type}/{id}
```

登录 POST 固定使用站点表单字段 `code/siteid/dosubmit/cookietime/username/password`，以 JSON `code == 200` 判定成功，并在登录后预热 `/mv/wkMn`。

搜索响应不是纯 JSON，影视列表位于 HTML 的 `_obj.search={...};`。插件读取其中的 `title/year/d/i`，再访问 `res/downurl`，从详情 `panlist` 提取真实资源链接。同一个搜索结果缓存 120 秒，Magnet/ED2K Provider 与迅雷秒传共同复用，避免为了两种来源重复打观影站。

诊断 API：

- `GET /api/v1/plugin/GuangYaTransferAssistant/viewing/nodes`
- `POST /api/v1/plugin/GuangYaTransferAssistant/viewing/nodes/refresh`
- `POST /api/v1/plugin/GuangYaTransferAssistant/viewing/session/test`
- `GET /api/v1/plugin/GuangYaTransferAssistant/providers/search?keyword=...`
- `POST /api/v1/plugin/GuangYaTransferAssistant/providers/test`

以上状态接口不会回显观影密码或 Cookie。

### 4. 观影迅雷分享 → 光鸭秒传

从 `panlist` 发现 `https://pan.xunlei.com/s/...` 后，迅雷路径不会把文件下载到 MoviePilot：

1. `/drive/v1/share`：取得 `pass_code_token`；
2. `/drive/v1/share/detail`：递归读取分享文件；
3. `/drive/v1/share/file_info`：必要时补 GCID、MD5、CID/下载链接；
4. MoviePilot 真实缺集 + Episode Resolver + 订阅质量规则筛选文件；
5. 光鸭 userres：`get_res_center_token -> check_can_flash_upload -> get_info_by_task_id`；
6. `get_res_center_token code=156` 直接视为秒传命中；
7. 秒传未命中清理未完成 upload task，继续低优先级来源。

CID 缺失时只读取迅雷文件**头 20KB + 1/3 位置 20KB + 尾 20KB**计算 SHA-1，不下载完整视频。插件不执行 OSS PUT，不进行本地跨盘中转，也不调用 MoviePilot DownloadChain。

迅雷状态接口：

- `POST /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/test`
- `GET /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/state`

## 配置页

最终配置页固定四块：

- **基础**：插件开关、接管订阅、目标目录、媒体限制、进度同步；
- **资源来源**：Telegram、观影节点池/账号/Cookie、PoW 自动验证、Magnet/ED2K API、迅雷秒传；
- **资源决策与云添加**：来源优先级、Episode Resolver 置信度、光鸭云任务轮询/重试；
- **高级**：历史页数、扫描上限、频道刷新、连载保护。

旧的 `viewing_login_path` 只为了升级兼容继续持久化，不再出现在 UI；真实登录路径固定为 `/user/login`。

### Magnet / ED2K 搜索接口

“磁力 / ED2K 搜索接口”每行格式：

`名称|类型|地址|密钥`

支持 `tgsearch`、`limitless`、`json`、`torznab`。候选仍进入 ResourceGroup，并继续执行 MoviePilot 订阅规则、缺集拆包和 taskId 防重复。

## ResourceGroup 与缺集拆包

迅雷秒传是 ResourceGroup 之前的最高优先级预检。它未覆盖的目标才进入：

`光鸭直接转存 > Magnet > ED2K`

电视剧始终先读取 MoviePilot 当前真实缺集：

- 迅雷分享：文件清单进入同一 `_planner_file_selection`，只秒传可靠映射到缺集的文件和字幕；
- 光鸭分享：只提交目标 `fileIds`；
- Magnet：`resolve_res` 后只把缺集对应 `fileIndexes` 交给 `create_task`；
- ED2K：只提交映射到缺集的链接；
- 同一个 Magnet 覆盖多个缺集时只建立一个光鸭任务；
- sample、花絮、无法确认集号的视频不顺带保存；
- `S01E05E06.mkv` 作为一个不可物理拆分文件处理。

秒传成功、光鸭分享等待落盘和 Magnet/ED2K 已创建任务都会形成 reservation，阻止后续来源重复获取相同剧集。

## Episode Resolver

支持 `S01E05`、`S01EP05`、`1x05`、`EP05`、`E05-E06`、`E05E06`、`第5集`、`第5话`、SP/OVA/OAD，以及有足够上下文的 `05.mkv`、`05~4K`、`Show.Name.05.2160p`。

`2026/1080/2160/264/265/266` 等规格数字会排除；`A.mkv / B.mkv / C.mkv` 不按文件顺序猜集。自动拆包默认置信度 `0.90`，低于阈值进入 `needs_review`，不会整包误存。

## Magnet / ED2K：光鸭原生云添加

Magnet/ED2K 继续复用 `光鸭云盘助手 (ShukGuangYaDisk)` 登录态与目录，调用：

`resolve_res -> create_task -> list_task -> 完成/原生重试`

接口为 `/cloudcollection/v1/resolve_res`、`/cloudcollection/v1/create_task`、`/cloudcollection/v1/list_task`、`/cloudcollection/v2/retry_task`。已有 `taskId` 只轮询/原生重试，重启后不重复 `create_task`。

## 固定分流

未接管订阅仍使用 MoviePilot 原生路线；已接管订阅的 MoviePilot 原生搜索、RSS 匹配和最终下载提交由硬门禁阻断。网络异常、观影节点不可用或资源暂缺时也不会静默回退本地下载器。

## 依赖与生产烟测

需要安装并登录同仓库的 `光鸭云盘助手 (ShukGuangYaDisk)`。本插件复用其运行时客户端、Token 刷新、目录创建、分享转存、userres 秒传和 cloudcollection 能力，不保存第二份光鸭登录凭据。

CI 可以覆盖协议解析、PoW 算法、节点切换、隐私边界、缺集筛选和秒传调用契约；**真实 GYING 账号登录 → 搜索 → 迅雷分享 → 光鸭账号秒传**仍需在实际 MoviePilot 环境用测试账号/Cookie 做生产烟测，因为站点节点、出口与会话验证会动态变化。
