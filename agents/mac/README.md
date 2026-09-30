# macOS Agent

`src/` 按实现职责组织；文件名、CMake target 和 vendor 编译选择保持不变。

| 目录 | 职责 |
|---|---|
| `src/platform/` | 平台 adapter、provider 装配、主线程调度、权限、日志桥与弱网设施 |
| `src/rtc/` | SDK 中立的 loader/backend 接口、RTC 调用管线、事件桥与公共词表 |
| `src/video/` | 视频 Host、视图登记、布局/统计叠层与合成视频源 |
| `src/vendors/agora/` | Agora loader、mock/real backend、调用注册、画面 probe 与词表 |
| `src/vendors/volcengine/` | 火山 loader、mock/real backend、调用注册、画面 probe 与词表 |
| `src/vendors/zego/` | ZEGO loader、real backend、调用注册、画面 probe 与词表 |
| `src/generated/` | 从 SDK Adapter 声明生成的 callback target 词表 |
| `demo/` | Agent 进程入口、WebSocket 传输与协议处理 |
| `tests/` | 原生 Mock 与真实 SDK 回归 |

CMake 仍只公开 `src/` 为头文件搜索根；include 使用带职责目录的路径，例如
`platform/platform_adapter.h`、`rtc/rtc_backend.h` 与 `vendors/agora/agora_sdk_loader.h`。
每个 vendor 变体只编译自己的实现，共享接口留在 `rtc/`；目录分组不增加新的库或运行时层。

生成词表由 `scripts/generation/generate_rtc_event_vocabulary.py` 维护，不手工编辑。
Mac 连接由 demo 中的 `DirectWebSocketTransport` / `NSURLSessionWebSocketTask` 拥有，Core 不提供另一套连接接口。PermissionManager 按 mock/real 构建选择确定性夹具或真实 OS 权限查询与异步请求。见 [ADR-043](../../docs/architecture.md#platform-boundaries)。
模块边界见[架构入口](../../docs/architecture.md)，验证选择与命令见
[验证合同](../../docs/development.md)。
