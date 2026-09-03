# 每日助手

每日助手把 MoviePilot V3 的推荐/发现能力与公共榜单统一成一个候选池，再通过光鸭转存助手现有的 `guangya_direct_subscribe` / GYSub 固定路线创建订阅。

默认只生成候选，不会因为榜单上榜就自动订阅。需要自动化时同时开启“自动 GYSub”并选择允许自动订阅的榜单；未选中的榜单仍只展示候选。

当前来源包括纪录片、日漫、综艺，Netflix 官方 Tudum Top10，HBO/Max、Apple TV+、Disney+、Crunchyroll、Amazon Prime、Amazon、Hulu 的 TMDB watch-provider 发现，猫眼，豆瓣，IMDb，TMDB 趋势，AniList，Bangumi 以及腾讯视频热播。榜单条目先尽量解析为 TMDB 身份；无法唯一识别的条目只展示，不会自动提交 GYSub。

GYSub 仍由光鸭转存助手执行，因此后续继续沿用现有的观影 GYING → 迅雷分享 → scriptVersion 1.1.3 JSON → 光鸭秒传 → MoviePilot 整理链路。