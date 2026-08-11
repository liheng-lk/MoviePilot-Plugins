# 光鸭云盘认证兼容说明

当前维护版保留两种登录方式：

## 1. 扫码登录（推荐）

设备码接口：

```text
POST https://account.guangyapan.com/v1/auth/device/code
```

请求包含：

```json
{
  "client_id": "aMe-8VSlkrbQXpUR",
  "device_id": "<32位设备ID>",
  "scope": "user profile sso offline_access"
}
```

二维码内容使用接口直接返回的 `verification_uri_complete`。

授权状态通过：

```text
POST https://account.guangyapan.com/v1/auth/token
```

轮询，成功后保存 `access_token` 与 `refresh_token`。

## 2. 短信登录（备用）

短信流程：

1. `/v1/shield/captcha/init` 获取 captcha token；
2. `/v1/auth/verification` 发送短信验证码并获取 `verification_id`；
3. `/v1/auth/verification/verify` 校验验证码并获取 `verification_token`；
4. `/v1/auth/signin` 获取 `access_token` 与 `refresh_token`。

两种登录方式最终共用同一套 Token、文件 API、WebDAV 与流媒体功能。
