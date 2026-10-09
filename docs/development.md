# 开发与验证指南

贡献流程见 [CONTRIBUTING.md](../CONTRIBUTING.md)。首次运行从 [快速入门](quickstart.md) 开始，真实 SDK 环境配置见 [Mac Console](mac-console.md)。

## 开发环境与目录

- 新 macOS 开发者可运行 `bash scripts/dev/setup_macos.sh` 安装 CMake、uv，并准备锁定的 Python 3.11 环境；追加 `--with-agora` 或 `--with-sdks` 可复用本地 SDK，缺失时再提供厂商下载地址；凭证仍需开发者自行填写，见 [Mac Console 环境设置](mac-console.md)。
- Python 3.11+、uv；原生 macOS 开发另需 macOS 13+、CMake 和兼容系统 SDK 的 Xcode/Swift 工具链。
- `server/tests/`、`python_sdk/tests/`、`tests/tooling/`、`tests/integration/` 保存回归测试；正式 SDK 用例位于 `test_cases/python/`。
- `test_cases/protocol_examples/` 是协议验证输入；`scripts/contracts/` 保存工具读取的 invariant catalog 与 manifest schema。进度测试使用 `tests/fixtures/` 中的固定夹具。
- `reports/` 是生成产物，不提交；私有设计、ADR、状态、历史、评审与个人经验保存在忽略目录 `.private/docs/`，公开开发与测试不依赖该目录。

## 按改动范围选择验证

所有编辑执行 `make format-check` 与 `git diff --check`。文档还需回读并检查链接；不要为纯文档改动运行所有 SDK 和覆盖率目标。行为改动按下面实际影响取并集，跨层执行链路改动补 Mock E2E。

| 改动范围 | 验证入口 |
|---|---|
| 协议、schema、用例声明 | `make test-protocol`；影响执行时加 `make test-server-quiet` |
| Server | `make type-server`、`make test-server-quiet` |
| Agent Core、日志 | `make test-agent-core`、`make test-logging` |
| macOS adapter、原生连接 | `make test-mac-mock`；直连改动加 `make test-mac-direct-agent-mock` |
| Python SDK、facade、callback 词表 | `make test-server-quiet`、`make test-protocol`、`make sdk-facade-check`、相关生成检查、`make coverage-python-sdk` |
| Mac Console | `make test-mac-console`；App/UI 包装加 `make test-mac-console-ui-smoke`；真实编排加对应 vendor Console gate |
| 真实 SDK backend、媒体证据 | 对应 vendor real gate；影响 Console 链路时加对应 Console gate |
| CI 选择、报告上传与敏感信息扫描 | `make test-ci-selection`、`make test-report-secrets`、`make report-secrets`，回读 CI 配置 |

`make test-server-quiet` 运行上面四个 Python 回归目录。失败先看 `reports/latest/server.pytest.log`，需要详细终端输出时用 `make test-server`。

### 常用命令与产物

| 命令 | 范围 / 主要产物 |
|---|---|
| `make test-protocol` | 协议样例、schema 与用例 metadata；`reports/latest/protocol.json` |
| `make test-e2e-mock` | HTTP/WebSocket、独立 Runner 与 Mock Agent；`reports/latest/report.json` |
| `make test-mac-agora-real` | Agora 原生场景；`reports/latest/mac_real.junit.xml` 与各 case JSON |
| `make test-mac-volcengine-real` | 火山原生场景；`reports/latest/mac_volcengine_real.json` |
| `make test-mac-zego-real` | ZEGO 原生场景；`reports/latest/mac_zego_real.json` |
| `make test-mac-console-agora` / `test-mac-console-volcengine` | 对应 vendor 的真实 Console 编排与报告 |
| `make test-mac-console-real` | 多 vendor 在统一 Server/Console 拓扑中的编排；不替代每家 SDK 的专项验证 |
| `make help` | 完整目标目录 |

测试入口和目录职责还可查阅 [脚本入口](../scripts/README.md) 与 [测试归属](../tests/README.md)。

## 结果与证据

- **passed**：该检查所声明的条件实际通过；明确说明使用的是 Mock 还是真实 SDK，以及设备与场景范围。
- **skipped**：所需 SDK、凭证或设备环境缺失。真实 gate 写 skipped artifact 并返回 0；不能记作行为通过。`test-ios` / `test-android` 当前也是 skipped 占位。
- **failed**：环境齐备后构建、注册、回调、断言或必需证据失败，命令应非零。不要吞掉失败、删除失败证据或把缺少媒体证据当作已通过。

调用结果、SDK callback、报告 artifact、真实媒体与人工观察各有范围。一次接口返回、一个 callback 或静态快照不能证明主观视听通过。需要画面证据的用例应检查实际首帧与 artifact；本机渲染视图 JPEG 不表述为远端用户截图。

修改行为测试时，说明具体故障、真实入口、独立预期结果与失败断言。身份、过滤、资源、cleanup 和终态等高风险路径补对应的故障注入或修复前失败、修复后通过的证据。Smoke 与覆盖率百分比不能代替这些断言。

### 覆盖率与 CI

Linux CI 执行格式、类型、协议、Python 回归、Python SDK 覆盖率、CI 选择和报告扫描；macOS 专项根据差异执行 Core、日志、Mock 与 Console 检查。真实 SDK 不在 hosted CI 自动执行，需要配置齐备的环境。

`coverage-python-sdk` 默认 95% 门禁，统计完整 SDK 源目录，包括未 import 文件。其他覆盖率按专项选择；选定硬门后，不得降低阈值、缩小生产分母、添加排除或删测试使其通过。真实 C++ 覆盖率统计被 export 的完整生产 `.mm` 文件；未链接源码或其他平台不能从 aggregate 百分比推断已验证。

报告上传前执行 `make report-secrets`。扫描失败阻止上传，但保留失败证据。文本扫描不证明媒体和二进制已审查；SDK 二进制、凭证和大型本地媒体不随仓库分发。

<a id="code-style"></a>
## 代码风格

- C++17；可恢复错误用结果类型，不跨模块边界抛异常。
- Python 3.11、类型注解；Server 生产代码使用 `make type-server` 检查。
- Swift Console 保持视图职责简洁，把可验证逻辑放在模型中。
- 代码注释默认中文，文件惯例或外部 API 合同要求其他语言时遵循其要求。说明原因、约束与所有权，避免复述代码。
- SDK 知识留在声明源、provider 与 vendor 实现中，遵守 [架构边界](architecture.md)。

## 提交与评审清单

- [ ] 一次改动只解决一个问题，保留无关修改。
- [ ] 行为、协议、schema 或验证入口变化时，同步相关公开指南与生成物。
- [ ] 记录实际命令、结果、报告路径，以及失败、跳过或未验证的范围。
- [ ] 测试确实能检测目标故障，清理失败不会被成功结果掩盖。
- [ ] 不提交本地 env、凭证、SDK 二进制、生成报告或 `.private/` 内容。
- [ ] 明确剩余工作；没有剩余项时直接说明。
