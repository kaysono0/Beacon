# 测试归属

| 目录 | 验证对象 |
|---|---|
| [server/tests/](../server/tests/) | Server API、设备运行时、Observation、Runner 管理与报告投影 |
| [python_sdk/tests/](../python_sdk/tests/) | BeaconSession、即时 facade 和 Python Runner |
| [tooling/](tooling/) | CI 选择、报告扫描、覆盖率/类型包装器、共享报告和证据映射工具 |
| [integration/](integration/) | registry 生成到消费、运行时架构约束、Mock Agent 和 Console 编排合同 |

原生组件测试保留在各自的 `agent_core/tests/`、`agents/mac/tests/` 和 Console `Tests/`。正式 SDK 测试用例源为 `test_cases/python/`，不属于上述 pytest 回归目录。

`make test-server` 和 `make test-server-quiet` 保留原命令名，运行上表全部 Python 回归；pytest 配置由 `server/pyproject.toml` 管理。聚焦调试时从 `server/` 执行 pytest 并指定对应目录或文件。`make test-e2e-mock` 单独验证真实 HTTP/WebSocket、独立 Python Runner 和 Mock Agent 链路。

验证选择和报告语义见 [验证合同](../docs/development.md)。
