# 光鸭转存助手 v1.9.3 交付验收

## 目标

v1.9.3 不再只解决“观影已经给出迅雷链接之后怎么秒传”，而是把整条链路收口：

`观影节点发现 -> 浏览器计算验证 -> 账号/ Cookie 会话 -> 搜索 -> downurl -> 迅雷分享 -> 光鸭秒传`

最终固定优先级：

`观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`

## A. GYING 节点完整性

观影域名会变化，因此不把业务绑定到一个固定域名。

实现：

- 默认发布/换址入口：`gying.page`、`gying.si`；
- 静态备用 seed 只作为发布页不可用时的兜底；
- 支持用户首选节点和手动备用节点；
- 中文 IDN / punycode 都会标准化；
- 节点列表缓存，避免每次搜索都访问发布页；
- 保存最近成功节点；
- 识别维护页、地址发布/换址页、HTTP 阻断和搜索失败；
- 失败节点进入 10 分钟冷却；
- 搜索失败自动清空 active node 并最多切换 3 次。

用户给出的 `https://www.星际穿越.com` 可直接作为“首选观影节点”，但插件不会假定它永远有效。

## B. GYING 浏览器计算验证

参考当前站点协议实现三类 challenge：

1. **远程 PoW**
   - `GET {node}/res/pow` 取 `N/x/t`
   - `y = (y*y) % N` 重复 `t` 次
   - `POST {node}/res/pow`，表单 `y={hex(y)}`
2. **内嵌 PoW**
   - 从 `const json={id,N,x,t}; const jss=...` 读取参数
   - 同样计算平方取模
   - 向当前 challenge URL 提交 `action=verify&id={id}&y={hex(y)}`
3. **旧版 challenge/diff/salt**
   - 枚举 nonce
   - 匹配 `sha256(str(nonce)+salt)`
   - 按 challenge 原顺序提交多个 `nonce[]`

PoW 运行有最大迭代限制，异常参数直接拒绝，避免错误页面造成无界 CPU 占用。访问 challenge、提交验证和重试原请求始终使用同一个 `requests.Session` 与稳定浏览器请求头。

验证 Cookie 与登录 Cookie 分开处理；每节点 Cookie 私下保存到 `viewing_session_state`。公开节点/状态 API 不返回 Cookie、观影密码或 challenge 数据。

## C. GYING 真实登录 / 搜索 / 详情接口

运行时固定使用站点实际接口：

```text
GET  {node}/
POST {node}/user/login
GET  {node}/search?q={keyword}&type=0&mode=2
GET  {node}/res/downurl/{type}/{id}
```

登录表单：

```text
code=
siteid=1
dosubmit=1
cookietime=10506240
username={username}
password={password}
```

JSON `code == 200` 才视为登录成功。成功后预热 `/mv/wkMn`，随后保存完整 Session Cookie。

搜索页从 `_obj.search={...};` 解析：

- `l.title`
- `l.year`
- `l.d`
- `l.i`

然后按 `d/i` 请求 `res/downurl`，递归定位详情中的 `panlist.name/url/type`。

Magnet/ED2K Provider 和迅雷秒传使用同一份 `_gying_raw_results`，短期缓存 120 秒，避免一个订阅先搜迅雷、随后又重复请求一次观影。

## D. 参考秒传脚本复用点

按用户提供的“光鸭秒传工具-全能版”复用迅雷/光鸭数据链路：

- 迅雷分享文件读取：`share_id + pass_code_token`；
- 迅雷文件元数据：GCID、MD5、size、可用下载链接；
- CID：只在需要时读取 3 × 20KB 样本计算 SHA-1；
- 光鸭秒传：`get_res_center_token -> check_can_flash_upload -> get_info_by_task_id`；
- `get_res_center_token code=156` 视为即时秒传成功；
- 未命中时清理未完成 upload task。

浏览器脚本中的整文件/OSS PUT 兜底没有移植。插件只做秒传；秒传未命中立即回退低优先级资源，避免 MoviePilot 主机承担跨盘流量。

## E. 迅雷分享协议

1. `GET /drive/v1/share`：传 `share_id` 和可选 `pass_code`，取得 `pass_code_token`。
2. `GET /drive/v1/share/detail`：分页并递归读取分享文件夹。
3. `GET /drive/v1/share/file_info`：文件缺 GCID/CID/download URL 时补全。

匿名分享请求不注入迅雷账户 Bearer，只发送分享读取所需的 client/device/captcha 头。

## F. 缺集、质量规则与防重复

- 继续读取 MoviePilot `_subscription_missing_episodes`；
- 迅雷文件清单复用已有 `_planner_file_selection`；
- 继续执行 `_subscription_resource_allowed`；
- 只对高置信目标集及其字幕做秒传；
- 成功秒传集加入 reservation，后续光鸭分享/Magnet/ED2K 排除同一集；
- 成功集同步已有 media facts；
- `xunlei_flash_state` 保存稳定指纹，重启后跳过已完成文件。

## G. 配置

观影：

- `viewing_enabled`
- `viewing_registry_urls`
- `viewing_base_url`（首选节点，可空）
- `viewing_node_urls`
- `viewing_auto_switch`
- `viewing_auto_challenge`
- `viewing_node_cache_minutes`
- `viewing_username`
- `viewing_password`
- `viewing_cookie`
- `provider_proxy`

迅雷：

- `xunlei_flash_enabled`
- `xunlei_flash_max_files`
- `xunlei_client_id`
- `xunlei_device_id`
- `xunlei_captcha_token`
- `xunlei_captcha_init_json`

旧 `viewing_login_path` 仅保留持久化兼容，不再出现在配置 UI；真实登录固定 `/user/login`。

## H. 诊断 API

观影：

- `GET /api/v1/plugin/GuangYaTransferAssistant/viewing/nodes`
- `POST /api/v1/plugin/GuangYaTransferAssistant/viewing/nodes/refresh`
- `POST /api/v1/plugin/GuangYaTransferAssistant/viewing/session/test`
- `POST /api/v1/plugin/GuangYaTransferAssistant/providers/test`

迅雷：

- `POST /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/test`
- `GET /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/state`

所有接口继续统一 Bearer 鉴权；状态结果不返回观影 Cookie/密码、迅雷 captcha token/init JSON/device ID 的原值。

## I. 安全边界

- 不调用 MoviePilot DownloadChain；
- 不调用 qBittorrent / Transmission / Aria2；
- Magnet/ED2K 仍只走光鸭 cloudcollection；
- 迅雷秒传不调用 `/userres/v1/flash_upload` 上传正文；
- 不执行 OSS PUT / Content-Range 整文件中转；
- 秒传 CID 计算最多读取约 60KB 迅雷样本；
- PoW challenge 参数有计算上限；
- 节点 URL 标准化会拒绝内嵌账号密码和 localhost/127.*；
- 失败不会伪装成成功，按既定优先级继续下一来源。

## J. 自动化验收

CI 必须至少覆盖：

- Python syntax；
- 仓库 Unit tests；
- GYING Unicode/punycode 节点归一化；
- GYING PoW 与 legacy nonce 算法；
- `_obj.search` 解析；
- 发布页/节点配置持久化；
- landing/maintenance/失败节点切换契约；
- GYING 公共 API 不泄露 Cookie/密码；
- 迅雷分享解析、GCID/CID、3×20KB 哈希；
- 光鸭 userres 秒传契约；
- 缺集 reservation 与 ResourceGroup 防重复；
- Magnet/ED2K 不重新接入 MoviePilot downloader。

## K. 仍需真实账号烟测的边界

自动化测试不能替代站点生产会话。合并前可以验证协议、算法、状态机和隐私边界；真实的：

`可用 GYING 节点 -> PoW -> 账号登录 -> 搜索 -> downurl -> 迅雷分享 -> 光鸭账号秒传`

仍需要在实际 MoviePilot + ShukGuangYaDisk 登录环境，用一个临时 GYING 测试账号或已验证 Cookie 完成最终生产烟测。
