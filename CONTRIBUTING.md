# Contributing

感谢参与 MoviePilot-Plugins。

这个仓库包含多个独立插件。提交前请先确认改动只影响目标插件，避免在一个 PR 里同时重构多个无关插件。

## Fork / Branch

推荐从最新 main 创建短生命周期分支：

```text
fix/<topic>
feature/<topic>
refactor/<topic>
docs/<topic>
```

PR 尽量小而可审计。不要把业务功能、全量格式化、文件大搬迁和版本升级混在同一个 PR。

## 测试

仓库最终以 `.github/workflows/validate.yml` 为准。

基础检查：

```bash
python -m compileall -q plugins.v2 plugins.v3
python -m unittest discover -s tests -v
```

V3 插件还应执行各自 contract runner。

### 光鸭转存助手

先阅读：

- `plugins.v3/guangyatransferassistant/ARCHITECTURE.md`
- `plugins.v3/guangyatransferassistant/DEVELOPMENT.md`

该插件实行 Authority-first 规则：优先修改既有领域 Authority，禁止继续用“一版一个 *_vXXXX.py 补丁层”的方式堆功能。

## Pull Request

PR 需要至少说明：

- 问题 / 需求；
- 根因；
- 行为变化；
- 测试；
- 是否需要实机验证；
- 回滚方法。

如果修改状态机、资源身份、缺集计算、转存提交或 MRO，必须包含对应回归测试。

## 安全原则

涉及远端删除、移动、覆盖、媒体身份、跨季转存、自动下载/云添加的修改必须 fail-closed。

不要在日志、测试夹具、Issue 或 PR 中提交真实 token、Cookie、密码、Device ID 或私有分享凭据。
