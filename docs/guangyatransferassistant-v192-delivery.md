# 光鸭转存助手 v1.9.2 交付验收

## 配置界面

- 最终配置表单只返回 4 个区域：基础、资源来源、资源决策与云添加、高级。
- 旧 mixin 表单仅用于读取 MoviePilot 动态订阅列表、光鸭目录选项和 defaults，不再把旧卡片/提示叠加到最终界面。
- 观影配置包含地址、登录路径、用户名/邮箱、密码、Cookie。
- Magnet/ED2K 搜索接口支持多行配置：`名称|类型|地址|密钥`。

## 外部搜索

- 支持 GYING 搜索页 + downurl 资源解析。
- 支持 tg-search、Limitless/相似 JSON、通用 JSON、Torznab。
- 只提取 Magnet/ED2K，不将外部搜索结果直接交给 MoviePilot 下载器。
- 自动补源仅发生在现有频道 ResourceGroup 没有产生可安全执行候选且仍存在缺集时。
- 自动绑定前必须通过媒体标题匹配；ED2K 还必须能高置信映射到当前缺集。

## 安全边界

- Magnet/ED2K 最终仍走 GuangYa cloudcollection。
- 已有 taskId 的任务不重复 create_task。
- 真实文件列表 resolve 后再次执行 MoviePilot 订阅质量规则。
- 用户名、密码、Cookie、外部 API Token 不进入状态页或 provider 搜索 API 响应。
- 标准账号密码登录失败或遇验证码时不绕过验证，提示改用已登录会话 Cookie。

## 回归

- v1.7 固定分流、RSS 门禁和最终下载断路器保持不变。
- v1.8 native cloudcollection / taskId 防重复保持不变。
- v1.9 ResourceGroup / Episode Resolver / needs_review 保持不变。
- v1.9.1 紧凑状态页保持不变。
