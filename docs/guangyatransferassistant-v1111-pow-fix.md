# 光鸭转存助手 v1.10.11：观影远程 PoW 实机修复

真实 MoviePilot 日志确认：内容节点已经下发 `browser_pow`，`GET /res/pow` 可取得挑战，`POST /res/pow` 也返回 HTTP 200，但 v1.10.10 因响应未出现预期 `success=true` 而在重试原请求前直接判失败。

本版按 PanSou 当前实现修正两个关键点：

1. 最短计算时长从取得 `N/x/t` 后、真正开始平方取模时计时；`GET /res/pow` 网络耗时不计入该窗口，并保留小幅安全余量。
2. `POST /res/pow` HTTP 200 后，即使响应确认字段发生漂移，也继续使用同一 Session 重试原请求；只有原请求仍返回 challenge 才最终判定失败。`success=true`、`code=200` 或 `browser_verified` 仅作为提前确认信号。

同时，业务 failover 只尝试真实 IDN 内容镜像；`gying.*` / `gyg.*` 发布换址域只用于地址发现，不再拖慢每次搜索。若验证失败且当前 Session 未使用 MoviePilot 代理，日志会提示检查“观影/外部搜索使用代理”。

安全边界不变：不记录 Cookie、PoW 参数、账号密码、验证码内容或点击坐标；汉字点击验证码仍由用户本人完成；Magnet/ED2K 仍使用光鸭原生 `cloudcollection`，不经过 MoviePilot 下载器。
