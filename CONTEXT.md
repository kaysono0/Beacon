# Beacon

Beacon 是面向任意 SDK 接口自动化验证的控制面和 Agent 框架。它用 Python SDK wrapper、结构化协议目标、运行期证据和断言规则验证不同 SDK 的真实接口行为。

## Language

**通用证据驱动测试框架**:
Beacon 当前的测试验证模型。Python 用例通过同步 `BeaconSession` 调用设备 SDK，基于 Observation 和普通 Python 断言判断接口行为。
_Avoid_: Agora 链路验证, SDK 日志验证, 多媒体链路测试框架

**SDK Test Intent**:
测试用例表达的 SDK 能力验证意图，不限定具体 SDK、平台或接口名。当前由普通 Python 用例与 generated typed facade 调用表达。
_Avoid_: SDK method, Agora command, media command

**Call Target**:
Protocol v2 中描述 SDK 调用目标的结构化对象，包含 sdk、class_name、function 和可选 overload。
_Avoid_: method 字符串

**Callback Target**:
Protocol v2 中描述 SDK 回调目标的结构化对象，包含 sdk、class_name、function 和可选 overload。
_Avoid_: event 字符串

**SDK Capability**:
某个 SDK Adapter 声明可独立验证的一项能力。一个 SDK Capability 可以映射到一个或多个真实 SDK 接口。
_Avoid_: API 路径, method 字符串

**SDK Interface Mapping**:
SDK Adapter 内部从 SDK Test Intent 到真实 SDK 接口、参数、返回值和事件的映射。
_Avoid_: Server 侧 SDK 特判

**SDK Registry Source**:
SDK Adapter 包内由人维护的能力、接口映射和证据映射定义。
_Avoid_: Server 配置

**SDK Registry Artifact**:
由 SDK Registry Source 编译出的标准 JSON，供 Server、CI 和测试编排读取。
_Avoid_: compiled registry

**Evidence**:
一次测试运行中由 Agent 或 Server 产生的运行期证据，类型包括 event、metric、state、artifact 和 log。
_Avoid_: 原始 SDK 回调, 纯日志

**Observation**:
即时远程控制运行时中不可变的运行事实，既可记录设备回调，也可记录框架 call/wait 的结果；回调本身不表示由某次调用导致。
_Avoid_: 已归因回调, 步骤结果副本

**Assertion**:
Python 用例对调用结果与 Observation 的判断，失败由 Runner 提交并影响 case/run 终态。
_Avoid_: 硬编码检查, 日志字符串匹配

**EvidenceStore**:
按 run、case、step、node 关联保存 Evidence 的记录集合。
_Avoid_: ResultCollector 混放区

**BeaconSession**:
Runner 注入的同步远程控制会话，固定 run/case 和设备 role，提供调用、Observation 查询/等待及 Native callback 后续操作注册。
_Avoid_: 独立 Client, 旧 recorder/executor

**Unsupported**:
测试目标 SDK 或平台声明不支持某个 SDK Capability 时的正式测试结果状态。
_Avoid_: Failed, Skipped

**SDK Adapter**:
把特定 SDK 的 interface、callback、stats 和 log 转换为 Beacon 通用语言的适配层。
_Avoid_: Server SDK 特判

**Domain Pack**:
某一类 SDK 的可复用测试意图、证据和断言模板集合，例如多媒体 SDK domain pack。
_Avoid_: Beacon 核心模型

## Example Dialogue

开发者：这个 SDK 接口调用成功后，Server 怎么判断行为正常？

领域专家：测试用例表达 SDK Test Intent，然后等待独立 Observation。接口成功事件是 event，质量或业务数值是 metric，Python 用例用这些事实执行断言。

开发者：SDK 日志能作为通过条件吗？

领域专家：日志是 log 类型 Evidence，主要用于诊断和报告。通过条件应优先使用 event、metric 和 state。

## Reading Order

- 开发者入口：[docs/README.md](docs/README.md)
- 执行链路与模块边界：[架构说明](docs/architecture.md)
- 验证与贡献规则：[开发与验证](docs/development.md)、[CONTRIBUTING.md](CONTRIBUTING.md)
- 当前执行面：用户在当前对话中明确选择的工作。
- 本机私有材料位于被忽略的 `.private/docs/`；个人待办位于 `.private/TODO.md`，仅由用户维护，不选择、排序或授权工作。公开开发和测试不要求这些文件存在。
