# 开发与验证工具

日常入口使用仓库根的 `make help`。Makefile 负责依赖、环境与失败处理；脚本是这些命令的实现，脚本之间使用带目录的模块导入。

| 目录 | 职责 |
|---|---|
| [dev/](dev/) | macOS 开发环境 setup、本地 Console App 构建、统一 Server 与手工环境 |
| [validation/](validation/) | 格式/架构/CI 检查、测试执行、Mock 与真实 SDK 门禁 |
| [generation/](generation/) | registry、Python facade、词表、用例导出和执行 manifest 生成 |
| [coverage/](coverage/) | 各组件覆盖率执行、汇总和证据映射 |
| [support/](support/) | 共享报告/JUnit、用例目录、run 等待、画面证据和控制文件辅助 |

脚本的回归测试归属见 [tests/README.md](../tests/README.md)。验证选择、产物和 passed/skipped/failed 含义由 [验证合同](../docs/development.md) 维护。
