# 磁力优先订阅 beta1 测试说明

该分支仅用于自动测试和后续 MoviePilot 实机测试，禁止在未完成验收前合并 main。

默认 `dry_run=true`：只搜索、中文字幕/季集过滤和记录候选，不创建光鸭离线任务，也不拦截 MoviePilot 原生链路。

通过以下门槛后才能进入生产接管阶段：
1. Python/JSON/单元测试全绿；
2. Torznab 真实搜索可用；
3. 中文字幕硬过滤实机正确；
4. 光鸭 resolve_res/create_task/list_task 真实可用；
5. 失败时 MoviePilot 原生订阅不受影响；
6. 重复触发不产生重复离线任务；
7. 才实现并验证“光鸭成功后阻止原生下载”的最终接管。
