# liheng-lk MoviePilot Plugins

这是由 **liheng-lk** 维护的 MoviePilot V2 插件合集。

MoviePilot 自定义插件源只需要添加一次：

```text
https://github.com/liheng-lk/MoviePilot-Plugins
```

## 插件

### 光鸭云盘助手 v1.0

光鸭云盘 MoviePilot 存储插件，支持扫码/短信登录、目录浏览、整理上传、上传进度监控、DNS/OSS 网络容错与 WebDAV。

### 每日新剧助手 v1.0

每天获取豆瓣近期热门/新剧，自动过滤：

- MoviePilot 已订阅的剧集；
- MoviePilot 媒体库中已经存在的剧集；
- 超出配置年份范围的旧剧；
- 低于配置评分的条目。

只把真正未拥有、未订阅的候选剧发送给用户，并生成当日序号。

支持：

```text
/newdrama
/newdrama_sub 1,3,5
/newdrama_sub 1-3
```

支持 MoviePilot v2.5.7+ 消息按钮回调的渠道，还可以直接点击剧名订阅。

## 致谢与参考

本仓库按照 MoviePilot V2 插件规范独立维护。开发过程中参考：

- jxxghp/MoviePilot-Plugins：MoviePilot V2 插件规范、豆瓣榜单、订阅及消息交互实现；
- ShukeBta/Guangyadisk：光鸭云盘早期存储实现；
- KoWming/MoviePilot-Plugins：光鸭扫码授权流程；
- DDSRem-Dev/guangyaclient：光鸭认证与短信登录接口行为。

具体代码继续遵守对应上游项目的开源许可证及版权声明。
