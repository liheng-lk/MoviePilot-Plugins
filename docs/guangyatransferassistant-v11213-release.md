# GuangYaTransferAssistant v1.12.13 发布验收

- 版本：`1.12.13`
- Build：`20260905-r59`
- 目标：修复 TV 媒体库已有剧集仍被迅雷 JSON 秒传重复写入的问题。

## 实机复现

用户现场：`择日飞升 (2026) S01 / #262`。

- MoviePilot 媒体库已存在 E01-E09；
- 光鸭频道随后成功转存 E10；
- 正确订阅进度已经显示 `10/30`，缺失 E11-E30；
- 同一轮人工完整检查中，迅雷链却又秒传 E01-E06。

这不是通知展示问题，而是迅雷最终缺集目标在不同完成事实刷新窗口内被放宽，允许已入库集重新进入 JSON import。

## v1.12.13 安全边界

TV 迅雷最终允许集固定为：

`MoviePilot library missing ∩ logical/fact missing - reservation - active source claim`

两个完成事实只允许通过交集继续缩小目标，不能互相覆盖或放宽。例如：

- 媒体库已有 E01-E09，因此 `library missing = E10-E30`；
- 频道 E10 刚完成，成功事实得到 `logical/fact missing = E01-E09,E11-E30`；
- 最终迅雷允许集只能是 `E11-E30`。

此外，在真正调用迅雷 JSON batch importer 前再次逐文件做物理硬过滤：

- 已入库/已完成集不能进入 `include_indexes`；
- 一个视频只要同时包含已有集和缺失集，整文件拒绝；
- 因此 `E09-E11` 不会为了 E11 顺带再次写入 E09/E10；
- 只包含 E01-E06 的迅雷分享最终 importer 调用次数必须为 0；
- 字幕只能跟随已经通过硬栅栏的视频；
- MoviePilot 媒体库缺集事实读取失败时，TV 迅雷 fail closed，本轮跳过迅雷并继续其它来源。

电影流程不使用剧集硬栅栏，保持原逻辑。

## 不变项

- 迅雷 JSON `scriptVersion 1.1.3` 协议不变；
- 来源优先级仍为 `观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K`；
- `/gycheck` 人工完整链不变；
- v1.12.12 GYING TMDB 官方别名召回保留；
- v1.12.10 迅雷跨季物理资源栅栏保留；
- 媒体身份、年份、质量、Episode Fence、reservation/source claim 均继续生效。

## 自动化验收

功能候选门禁：

- Python syntax：通过；
- Root Unit Tests：95/95；
- GuangYa V3 contracts：497/497（正式发布迁移前）；
- ShukGuangYaDisk / DailyNewDrama 回归：通过；
- dependency manifests / JSON / generated artifacts：通过。

正式 v1.12.13 发布门禁：

- Root Unit Tests：95/95；
- GuangYa V3 contracts：502/502（包含 10 条 v1.12.13 物理硬栅栏测试 + 5 条发布契约）；
- ShukGuangYaDisk / DailyNewDrama 回归：通过；
- V3 dependency manifests：通过；
- JSON indexes：通过；
- No generated Python artifacts：通过。

发布前还必须通过 PR merge-ref 标准 CI；合并后必须再次通过 `main` push CI。
