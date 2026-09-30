# Server 代码入口

HTTP/WebSocket 接入和生产组件装配从 `app/main.py` 开始；网关协议分派见 `app/api/gateway.py`。

| 目录 | 职责 |
|---|---|
| `app/api/` | HTTP/WebSocket 合同、鉴权、网关与 Console API 投影 |
| `app/devices/` | 设备/会话模型、在线设备、连接生命周期与下行分发 |
| `app/runs/` | 用例发现、角色解析、Runner 进程、即时调用、run 生命周期与快照 |
| `app/observations/` | 不可变运行事实的模型、接入、查询、等待和存储 |
| `app/reporting/` | 历史 Evidence、日志、artifact 元数据与报告投影 |
| `app/sdk/` | Registry 消费、SDK 参数扩展及测试 token 签发 |
| `app/common/` | 配置、错误、Protocol 接口、脱敏与结构化 target 合同 |
| `tests/` | Server 组件回归 |

模型与实现保留原文件名，从其所属包直接导入，例如
`app.devices.device_models`、`app.runs.run_runtime` 与 `app.observations.observation_service`。
包入口不聚合导出；`main.py` 仍负责唯一生产组件装配，目录分组不增加新的运行时层。
正式测试执行使用 Runner 和 `BeaconSession`。新增 SDK 能力由 adapter/registry 声明，
Server 的通用运行时不承载 vendor 业务。

模块边界见[架构规则](../docs/architecture.md)，验证命令见
[验证合同](../docs/development.md)，测试目录见[测试归属](../tests/README.md)。
