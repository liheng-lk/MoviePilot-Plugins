# 光鸭转存助手 v1.9.3 交付验收

## 目标

把观影 GYING 返回的迅雷分享接入光鸭秒传，并放到所有资源来源之前。最终固定优先级：

`观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`

## 参考脚本复用点

实现按参考“光鸭秒传工具-全能版”的迅雷/光鸭数据链路复用：

- 迅雷分享文件读取：`share_id + pass_code_token`；
- 迅雷文件元数据：GCID、MD5、size、可用下载链接；
- CID：只在需要时读取 3 × 20KB 样本计算 SHA-1；
- 光鸭秒传：`get_res_center_token -> check_can_flash_upload -> get_info_by_task_id`；
- `get_res_center_token code=156` 视为即时秒传成功；
- 未命中时清理未完成 upload task。

浏览器脚本中的整文件/OSS PUT 兜底没有移植到 MoviePilot 插件。插件只做秒传；秒传未命中立即回退低优先级资源，避免 MoviePilot 主机承担跨盘流量。

## 观影 -> 迅雷

1. 复用 v1.9.2 的观影地址、Cookie/标准表单登录。
2. 搜索 MoviePilot 当前订阅标题、年份、季。
3. 调用观影 `res/downurl`。
4. 从 `panlist.url` 中提取 `https://pan.xunlei.com/s/...` 与邻近提取码。
5. 同一 `share_id` 去重，优先保留带提取码的候选。

## 迅雷分享协议

1. `GET /drive/v1/share`：传 `share_id` 和可选 `pass_code`，取得 `pass_code_token`。
2. `GET /drive/v1/share/detail`：分页并递归读取分享文件夹。
3. `GET /drive/v1/share/file_info`：文件缺 GCID/CID/download URL 时补全。

匿名分享请求不注入迅雷账户 Bearer，只发送分享读取所需的 client/device/captcha 头，避免他人分享出现 owner 身份冲突。

## 秒传与哈希

- GCID 优先采用迅雷 `hash/gcid` 40 位值。
- MD5 若存在且为 32 位 hex 则参与光鸭秒传探测。
- CID 若迅雷已返回则直接使用；否则只对迅雷下载 URL 发三个 Range 请求：文件头 20KB、1/3 位置 20KB、末尾 20KB，拼接后计算 SHA-1。
- 不下载完整视频文件。

光鸭目标目录通过当前 ShukGuangYaDisk 运行时 `get_folder` 创建/定位，随后调用 userres 秒传接口。秒传状态持久化到 `xunlei_flash_state`，完成文件按 subscription/share/file/gcid/path 稳定指纹去重。

## 缺集与防重复

- 继续读取 MoviePilot `_subscription_missing_episodes`。
- 把迅雷文件清单转成已有 ResourcePlanner 的 `btResInfo/subfiles` 形态，复用 `_planner_file_selection`。
- 继续执行 `_subscription_resource_allowed`，不绕过订阅质量/include/exclude 规则。
- 成功秒传的集加入运行时 reservation，再进入下层光鸭分享/Magnet/ED2K 时会被排除。
- 成功集同步到现有 media facts；重复运行可从 `xunlei_flash_state` 跳过已完成文件。

## 配置

新增：

- `xunlei_flash_enabled`，默认开启；
- `xunlei_flash_max_files`；
- `xunlei_client_id`；
- `xunlei_device_id`；
- `xunlei_captcha_token`；
- `xunlei_captcha_init_json`。

可直接配置 captcha token；也可以粘贴浏览器开发者工具中 `shield/captcha/init` 的 JSON 请求体，用于 token 失效后重新初始化。所有字段加入 `_save_config`，不会因固定路由异步写盘丢失。

## API

- `POST /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/test`
- `GET /api/v1/plugin/GuangYaTransferAssistant/xunlei/flash/state`

状态 API 不回显 captcha token、captcha init JSON 或 device ID。

## 安全边界

- 不调用 MoviePilot DownloadChain。
- 不调用 qBittorrent / Transmission / Aria2。
- 不调用光鸭 `/userres/v1/flash_upload` 上传正文。
- 不执行 OSS PUT / Content-Range 整文件中转。
- 仅在秒传 CID 计算时最多读取 60KB 迅雷文件样本。
- 秒传失败后回退现有光鸭分享、Magnet、ED2K，不把失败伪装成成功。
