# Beacon 开发者文档

首次了解项目成果和演示，请先看 [README](../README.zh-CN.md)。本目录保留从运行、编写用例到接入 SDK 所需的开发者指南。

| 你要做什么 | 从这里开始 |
|---|---|
| 跑通第一个测试 | [快速入门](quickstart.md) |
| 编写 Python 用例、等待回调、编排多个设备 | [Python 用例编写](python-test-authoring-guide.md) |
| 配置真实 SDK、启动服务和 Mac App | [Mac Console](mac-console.md) |
| 接入一个新的 SDK | [SDK 接入](sdk-adapter-integration-guide.md) |
| 理解执行链路和模块职责 | [架构说明](architecture.md) |
| 选择验证命令、准备贡献 | [开发与验证](development.md) |

组件目录还有贴近源码的入口：[Mac Agent](../agents/mac/README.md)、[Server](../server/README.md)、[脚本](../scripts/README.md)、[测试](../tests/README.md)。贡献流程见 [CONTRIBUTING.md](../CONTRIBUTING.md)，术语见 [CONTEXT.md](../CONTEXT.md)。

`assets/` 保存公开演示资源。协议示例位于 `test_cases/protocol_examples/`，工具使用的合同数据位于 `scripts/contracts/`；它们是验证输入，不计入开发者文档。
