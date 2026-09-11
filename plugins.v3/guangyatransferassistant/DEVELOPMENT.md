# 开发指南

## 1. Fork 后的推荐流程

```bash
git clone <your-fork>
cd MoviePilot-Plugins
git remote add upstream <upstream-repository>
git fetch upstream

git checkout -b fix/short-topic
```

分支建议：

- `fix/<topic>`：bug；
- `feature/<topic>`：单一功能；
- `refactor/<topic>`：行为不变的结构收口；
- `docs/<topic>`：文档。

一个 PR 只解决一类问题。

## 2. 开始改代码前

先回答三个问题：

1. 这个改动属于哪个 Authority？
2. 是否能修改已有 Authority，而不是新增一个版本补丁文件？
3. 哪一条 Final Plugin E2E 可以证明不会破坏完整链？

找不到 Authority 时先读 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 3. 最小开发循环

```bash
python -m compileall -q plugins.v3/guangyatransferassistant
python tests/v3/guangyatransferassistant/run_contract_tests.py
```

需要完整仓库验证时执行与 `.github/workflows/validate.yml` 等价的步骤。

## 4. 调试原则

优先记录：

- subscribe_id
- run_id
- media / season
- source type
- share_id / source_id
- requested / resolved / transfer episodes
- target path
- taskId
- final verification state

不要用“成功 / 失败”一个布尔值概括所有阶段。

## 5. 新功能规则

新增来源时必须复用：

- `episode_target_v210` 的真实目标；
- 当前身份门禁；
- `core_pipeline_v11214` 的最终文件边界；
- 现有 reservation / claim；
- 现有完成判定；
- 现有 diagnostics / source trace。

禁止新建第二套：

- 缺集计算；
- 完成状态；
- scheduler；
- 媒体身份算法；
- MoviePilot 原生下载 fallback。

## 6. Bug 修复规则

每个 bug 至少需要一条回归测试，测试名称应描述用户场景，而不是内部函数名。

推荐：

`test_page_check_missing_channel_then_external_same_run`

不推荐：

`test_fix_20260912`

## 7. Refactor 规则

结构重构必须满足：

1. 行为测试先存在；
2. 先合并代码，再删旧 wrapper；
3. 同一次提交更新 import / MRO / tests；
4. Final Plugin E2E 必须绿；
5. 删除的兼容层不能在仓库继续残留死引用。

## 8. 提交信息

建议 Conventional-style 但不强制：

```text
fix(guangya): ...
refactor(guangya): ...
test(guangya): ...
docs(guangya): ...
```

避免：

`update`
`fix bug`
`new version`

## 9. PR 必须说明

- 用户问题；
- 根因；
- Authority；
- 是否改变业务语义；
- 修改文件；
- 测试；
- 是否真实环境验证；
- 回滚方式；
- 是否新增 MRO / 新模块。

## 10. 发布

版本号以 `plugin.json` / `package.v3.json` / 最终插件类为单一一致性合同。

README 不再堆叠版本日志。版本说明进入 [CHANGELOG.md](CHANGELOG.md)。

CI 通过后仍要区分：

- static / contract pass；
- simulated final-plugin E2E pass；
- real-world smoke pass。

不要把前两者写成“生产已验证”。
