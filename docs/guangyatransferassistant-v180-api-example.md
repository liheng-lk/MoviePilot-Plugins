# v1.8.0 API 示例

以下示例省略 MoviePilot 插件 API 的公共前缀与登录鉴权头。

```json
POST /source/add
{
  "subscribe_id": 123,
  "uri": "magnet:?xt=urn:btih:...",
  "dispatch": true
}
```

```json
POST /viewing/ingest
{
  "subscribe_id": 123,
  "uri": "ed2k://|file|Show.S01E01.mkv|123456|0123456789abcdef0123456789abcdef|/",
  "dispatch": true
}
```

成功绑定后，该订阅进入光鸭固定分流；Magnet/ED2K 由光鸭 cloudcollection 原生云添加处理，MoviePilot 本地下载器不会接到该来源。
