# Volcengine RTC AccessToken（vendored）

本目录是火山引擎官方 Python Token 生成示例的**逐字副本**，用于服务端签发火山 RTC Token。

| 项 | 值 |
| --- | --- |
| 来源仓库 | https://github.com/volcengine/rtc-aigc-embedded-demo |
| 源文件 | `server/src/AccessToken.py` |
| 上游 commit | `2bb1bf2dbbf40bb09ab59c1c0c39c84c797a34db`（2025-01-16） |
| 许可 | MIT（文件头保留 `Copyright (2025) Beijing Volcano Engine Technology Ltd.` 与 SPDX 标识） |
| 运行期依赖 | 无：只用 Python 标准库（`base64` / `hmac` / `random` / `struct` / `time` / `hashlib` / `collections`） |

`sha256(AccessToken.py) = 35d5fc9178ed5b275ef8ac546982bb8b9217b223f5b985fce58df9dc01d10560`

## 为什么 vendor 而不是加依赖

上游没有发布可索引的 Python 包（只提供示例源码），而 ADR-036 要求 Server 核心不得硬依赖任何具体 SDK 的运行时实现。逐字 vendor 一段纯标准库代码，既满足「核心依赖表不出现火山包」，又保持实现来自官方而非自行复刻。

## 用法（与上游示例一致）

```python
from vendor.volcengine_rtc_token import AccessToken

expire_at = int(time.time()) + ttl_seconds
token = AccessToken.AccessToken(app_id, app_key, room_id, user_id)
token.add_privilege(AccessToken.PrivSubscribeStream, expire_at)
token.add_privilege(AccessToken.PrivPublishStream, expire_at)
token.expire_time(expire_at)
token_str = token.serialize()
```

## 维护约定

- **不要就地修改本文件**。若需升级，重新从上游取同路径文件、逐个核对 diff，并同步更新本 README 的 commit 与 sha256。
- 该文件属于第三方代码，不参与本仓库的类型检查与格式化口径；Server 侧的封装在 `server/app/sdk/volcengine_token.py`。
