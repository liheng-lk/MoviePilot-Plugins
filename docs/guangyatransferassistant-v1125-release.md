# 光鸭转存助手 v1.12.5 发布验收

## 发布标识

- 插件版本：`1.12.5`
- Build：`20260904-r51`
- MoviePilot：V3，`system_version >= 3.0.0`
- 固定来源优先级：`观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`

## 调度语义

- 频道保持 5 分钟 Push 快车道，只消费已经到达的频道资源，不因频道 tick 主动访问 GYING。
- AiringDue 每小时运行，只选择今天应播、MoviePilot 仍确认缺失、且未被 reservation/source claim 覆盖的媒体。
- 今日到期媒体使用独立 60 分钟外部检索窗口，并进入既有完整来源链，而不是只执行单一 GYING 通道。
- 非更新日剧集不主动访问外部资源站；稳定更新星期可作为调度事实。
- 日历服务异常进入短退避，同时保留有界 fallback，避免追更永久冻结。
- 每日 04:10 全员复核先消费频道，再重算真实剩余缺口并强制补漏。

## 安全边界

- MoviePilot 媒体库仍是“已入库”的强事实来源。
- 迅雷 JSON 仍完整生成，但实际导入只允许当前真实缺集与高置信文件索引。
- 成功集、reservation 与 source claim 共用跨来源终止栅栏，避免同集重复秒传、直接转存或 cloudcollection。
- Magnet/ED2K 仍调用光鸭原生 `cloudcollection`，不经过 MoviePilot 本地下载器。
- 媒体身份、年份、季号、资源质量、Episode Resolver 与完成回执门禁保持原有权威链路。

## 发布门槛

正式合并前必须满足：

1. `plugin.json`、`package.v3.json` 与运行入口版本完全一致为 `1.12.5`。
2. 运行入口 Build 为 `20260904-r51`。
3. 当前运行层不存在 `r50-preview` / `r51-preview` 发布标记。
4. Python 语法检查通过。
5. 全仓库 unittest 通过。
6. GuangYaTransferAssistant V3 contract tests 全部通过。
7. V3 dependency manifests 与 JSON indexes 检查通过。
8. PR 合并后的 `main` 再执行一次同套 CI 并保持全绿。
