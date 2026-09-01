# 光鸭转存助手 v1.9.4 交付验收

## 版本

- 插件版本：`1.9.4`
- Build：`20260901-r8`
- 固定资源优先级：`观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`

## 本次完整性收口

1. GYING 节点身份统一：中文 IDN 与 punycode 合并；当前内容节点仅作为种子，不作为硬编码唯一入口。
2. Cookie 域隔离：手工 Cookie 只绑定首选节点；自动 failover 不跨域携带登录态。
3. 搜索降级：零结果才从“标题+年份+季”退到“标题+年份”再退到纯标题，候选年份同时存在时必须一致。
4. 节点故障：Angie/伪 404/阻断页进入 failover，不误判资源为空。
5. 迅雷身份：稳定 Device ID、captcha/client/device 一致性、`shield/captcha/init` 自动初始化。
6. 迅雷匿名分享：分享请求移除 Authorization；GCID 缺失时按同 parent_id + `with_audit=false` 二次读取。
7. 光鸭秒传边界不变：`get_res_center_token -> check_can_flash_upload -> get_info_by_task_id`；`code=156` 直接成功；CID 缺失只读 3×20KB 样本，不下载整文件。
8. ResourceGroup、Episode Resolver、MoviePilot 真实缺集、订阅质量规则、reservation 与 taskId 幂等全部保留。
9. Magnet/ED2K 继续仅使用光鸭原生 cloudcollection，不进入 MoviePilot 下载器。
10. 配置页四区、状态页五区继续保持紧凑结构，协议级设置下沉高级区。

## 自动化验收

必须通过仓库 `Validate MoviePilot Plugins` 的 Python syntax、Unit tests、V3 plugin contract tests、dependency manifests、JSON indexes 与生成物检查。

## 仍需实机验证

CI 无法替代动态站点与账号会话。最终生产烟测仍需要实际 MoviePilot + 已登录光鸭环境，以及临时 GYING 测试账号/Cookie，验证：

`节点发现 -> PoW/验证 -> 登录 -> /search -> /res/downurl -> 迅雷分享 -> 光鸭秒传 -> MoviePilot 缺集/订阅进度`。
