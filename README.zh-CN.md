# Beacon

**用 Python 驱动真实设备 SDK，在一个控制台里看到调用、回调、媒体画面和测试结果。**

Beacon 是基于 Python 的设备 SDK 自动化测试框架（SDK testing / test automation），将 Native SDK 接口调用、声明式回调 Hook、多设备编排与 macOS 可视化控制台连成一条完整测试流程。当前已接入 Agora、火山引擎（Volcengine）和 ZEGO Express，覆盖实时音视频（RTC）场景中的接口、回调与多端音视频测试。

[English README](README.md)

## 先看成果

[![Beacon 产品演示：加入房间回调、四宫格与九宫格](https://raw.githubusercontent.com/kaysono0/MyPicList/main/beacon-product-demo-poster.jpg)](docs/assets/beacon-demo/beacon-product-demo.mp4)

[观看约 53 秒的产品演示](https://github.com/user-attachments/assets/bc1f40c0-0c34-48fa-861d-ca6bee3e56c1)，保留原录音和中英字幕。视频展示了：

- **接口与回调验证**：在 Console 中运行 Agora 加入房间用例，查看执行记录和实际回调。
- **多路视频场景**：运行四宫格、九宫格视频用例，直接看到渲染画面。
- **从执行到结果**：在同一个界面选择用例、发起运行并查看结果。

## Beacon 的亮点

### 用普通 Python 表达测试意图

SDK 调用、回调等待和结果断言都写在 Python 用例里，每次调用即时在设备上执行。测试作者可以按业务流程组织用例，复用 Python 的条件、循环和辅助函数。

### 同时验证调用结果与后续行为

接口返回值、异步回调、状态和媒体指标分别记录，分别判断。用例可以检查“调用是否成功”，也可以继续验证“预期回调是否到达、字段是否正确”，每条记录都保留所属测试与设备的上下文。

### 用 defer 简化回调测试

测试脚本要在 SDK 回调触发时继续操作，需要衔接异步事件、后续调用和结果检查。对于已接入的 SDK 回调与操作，Beacon 用 `defer` 把“收到哪个回调、执行哪些操作”提前注册到设备 Agent。匹配回调到达时，预设操作在 Native 回调处理过程中本地执行，无需等待 Python 再下发操作，减少测试作者处理跨进程通信与回调协调的工作。

回调中的操作与普通接口调用（invocation）复用同一套调用执行器和接口实现。Agent 将规则匹配情况和每项操作的错误码、返回值随回调记录上报，Python 用例等待该记录后即可断言，形成“预先注册 → 本地触发与执行 → 结果断言”的完整测试流程。

详见[即时调用与回调设计](docs/architecture.md#callback)。

### 在一个用例里编排多个设备

用例通过 primary、peer 等角色控制不同设备，组织发布端、接收端和多路参与者的协作场景。各设备的调用、回调与资源保留独立上下文，可以在一次测试中检查多端行为。

### 让音视频测试结果看得见

macOS Console 集中展示用例、运行进度、执行记录和日志，并支持报告导出。音视频用例还可以展示本地与远端画面、采集视图快照，让接口验证与实际媒体表现一起进入检查流程。

### 多 SDK 接入与跨平台扩展

Agora、火山引擎和 ZEGO Express 已接入同一框架与 Console，各自保留原生 SDK 的接口和生命周期。SDK 差异由适配层承接，用例编写、运行控制和结果查看共用一套流程。

平台无关的协议、调用与回调处理放在公共 Agent Core，连接、权限和 SDK 宿主由各平台适配层负责，为跨平台接入提供共用基础。当前已落地 macOS，iOS / Android Agent 尚未开始。

## Quick Start

先体验 Mock 链路，无需安装厂商 SDK 或配置凭证；再按需运行真实 SDK。

1. **准备 Mac 开发环境**：运行 `bash scripts/dev/setup_macos.sh`；安装真实 SDK 时追加 `--with-sdks` 并提供厂商下载链接。然后按[快速入门](docs/quickstart.md)运行 Mock 用例并查看报告。
2. **体验真实 SDK 与 Console**：按 [Mac Console 操作指南](docs/mac-console.md)配置 SDK、凭证与权限，启动服务和 App。
3. **编写自己的用例**：从 [Python 用例编写指南](docs/python-test-authoring-guide.md)了解 SDK 调用、回调等待和资源清理。

组件职责与执行链路见[架构总览](docs/architecture.md)。

## 代码地图

| 目录 | 职责 |
|---|---|
| [`server/`](server/README.md) | FastAPI 控制面、设备/run 生命周期、Runner 监督、Observation 和报告 |
| `python_sdk/beacon_test/` | `BeaconSession`、生成的 typed facade、Python Runner |
| `test_cases/python/` | 可运行的 SDK 测试用例 |
| `agent_core/` | 平台无关的 C++ 协议、调用、资源与日志 |
| `agents/mac/` | macOS provider 接入、权限、Native mock/real SDK 后端 |
| `apps/mac_test_console/` | SwiftUI 用例浏览、运行控制、Observation 展示、报告导出 |
| `sdk_adapters/`、`sdk_registry/` | 能力源、schema 和编译后的 Registry artifact |
| [`scripts/`](scripts/README.md) | 开发、验证、生成、覆盖率和共享工具 |
| [`tests/`](tests/README.md) | 工具回归与跨组件合同 |
| `docs/` | 必要的开发者指南与公开演示资源 |

组件测试跟随组件，例如 `server/tests/`、`python_sdk/tests/`、`agent_core/tests/` 和 Console 的 `Tests/`。Mock E2E 由 `scripts/validation/` 驱动。

## 真实 SDK 与当前状态

项目处于早期阶段（0.1.0）。macOS 已接入 Agora、火山和 ZEGO，各家有独立的 SDK、凭证和验证要求。Mock 通过不证明真实 SDK 或媒体行为通过。

iOS/Android Agent 和真实操作系统级弱网注入仍属后续工作。Server 支持内存运行与 opt-in JSONL 快照。实现边界见[架构说明](docs/architecture.md)。

macOS 原生开发需要 macOS 13+、CMake，以及与系统 SDK 兼容的 Xcode 工具链。SDK 配置、Server/App 启停、摄像头权限和真实验证统一见 [Mac Console 操作指南](docs/mac-console.md)。

## 文档与贡献

[文档地图](docs/README.md)按读者任务导航，覆盖运行、用例编写、SDK 接入、架构与验证。

参与开发先读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题按 [SECURITY.md](SECURITY.md)反馈。验证命令和 passed/skipped/failed 语义由 [开发与验证指南](docs/development.md)维护。

## 许可

[MIT](LICENSE)。仓库不分发 vendor SDK 和本地凭证，见 [THIRD-PARTY.md](THIRD-PARTY.md)。
