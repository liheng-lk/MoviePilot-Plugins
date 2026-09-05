# GuangYaTransferAssistant v1.12.14 发布验收

- 版本：`1.12.14`
- Build：`20260905-r60`
- 目标：把资源发现、媒体身份、真实缺口、物理文件与最终写盘收口成跨来源统一不变量，避免漏资源、串媒体和已有剧集重复进入云盘。

## 1. 来源矩阵

频道与观影 GYING 均允许产生：

1. 光鸭分享 → 直接增量转存；
2. 迅雷分享 → JSON 1.1.3 秒传；
3. Magnet → 光鸭原生 cloudcollection；
4. ED2K → 光鸭原生 cloudcollection。

频道迅雷提取码只允许来自同一条 Telegram 消息；观影光鸭分享只在当前订阅线程中临时注入 ResourceGroup，不污染持久频道索引。

## 2. 媒体身份

发现标题只做候选预筛，最终以实际分享/resolve payload 为准。明确的标题、年份、Season 冲突硬拒绝。TV/动漫可以使用同一 TMDB ID 返回的官方英文/原始标题扩大 GYING 精确召回，但禁止编辑距离、拼音或其它模糊作品猜测。

## 3. TV 权威缺口

最终允许写盘集合必须满足：

```text
allowed = MoviePilot library missing
          ∩ logical/fact missing
          - reservation
          - other active source claims
```

当前正在 resolve/create 的 source 必须从 `other active source claims` 中排除，不能自己把自己扣空。MoviePilot 媒体库事实无法可靠读取时，TV 最终写盘 fail closed。

## 4. 不可分割物理文件

所有来源统一遵循：

```text
actual physical video episodes ⊆ allowed missing
```

示例：当前只缺 E11。

- `Show.S01E11.mkv` → 允许；
- `Show.S01E09-E11.mkv` → 拒绝整文件；
- `Show.S01E09-E12.mkv` → 拒绝整文件；
- 已入库/已完成/其它来源在途的集数不能因为切换来源重新进入 allowed。

## 5. 来源优先级与短路

固定优先级：

```text
观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K
```

前一来源一旦覆盖当前真实缺口，后续来源不再提交。Magnet/ED2K 不经过 MoviePilot 下载器。

## 6. 发布门禁

候选业务门禁在公开版本迁移前已全绿：GitHub Actions run `33962451418`，包括 Python syntax、95 个根单测、GuangYa V3 合同、依赖 manifest、JSON 索引和生成物检查。

正式发布仍要求：

- 迁移 `__init__.py / plugin.json / package.v3.json` 到 v1.12.14/r60；
- 当前版本合同全部迁移；历史 v1.12.13/v1.12.12/v1.12.10 模块标记继续保留；
- PR 正式 CI 全绿；
- 合并 main 后 main push CI 再次全绿。

## 7. 正式迁移结果

一次性 release workflow 已在提交前执行与仓库正式 CI 等价的完整验证，并在全部门禁通过后生成正式元数据迁移提交 `9d41699344372afabadf73943c3b0e79d50fb02c`；临时迁移脚本与临时 workflow 已在同一提交中自删除。

该 bot-authored 提交在 GitHub PR 安全策略下显示为 `action_required`，不作为测试失败处理。本次人工文档提交用于重新触发标准 PR CI；只有该 CI 与合并后的 `main` push CI 均为全绿，v1.12.14 才视为发布完成。
