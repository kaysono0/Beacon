# 新 SDK 接入指南：以 ZEGO Express macOS 真实链路为例

本文面向要把一个新的 SDK 接入 Beacon 的开发者。它以 `zego_express` 为已验证范例，说明从 SDK 原生接口到 Python 用例、真实 Mac Agent 和 Mac Test Console 的完整接入链路。

目标不是把新 SDK 改写成 Agora、火山或某个“通用 RTC API”。Beacon 共享的是声明编译、协议、Evidence、Assertion、报告和 Console 编排；房间/频道、用户身份、token、回调、画布、媒体源和资源释放仍由供应商原生语义决定。

## 先确定接入边界

在建文件之前，先写清四件事：

1. SDK 的原生对象模型和最小业务闭环。例如 ZEGO 的 `ZegoExpressEngine`、`loginRoom`、`startPublishingStream`、`startPlayingStream` 与 `ZegoEventHandler`。
2. 首个可验证场景。建议从“创建 → 连接/登录成功回调 → 释放”开始，再扩展到双端媒体。
3. 目标平台和运行形态。本文范例是 macOS Objective-C Framework，目标是一个 vendor 专属的 native Agent binary，不能和另一家媒体栈混编进同一进程。
4. 通过条件。调用返回成功不等于 SDK 已工作；至少要有原生回调或状态 Evidence。若验证画面，还要定义首帧和本地视图 artifact 的判定。

不要先修改 Server 来识别新 SDK。Server 只消费编译后的 Registry Artifact；新 SDK 的知识应保留在 adapter source、供应商 Agent 和 Python 用例中。

## 接入地图

```text
供应商 SDK Framework / 原生回调
        │
        ▼
Mac vendor build variant + loader + backend + providers
        │  callbackEventRequest / artifact
        ▼
SDK Adapter Source ──编译──► Registry Artifact ──生成──► typed Python facade
        │                                                    │
        └────────────────────────────────────────────────────┤
                                                             ▼
                                              Python Test Source / Assertions
                                                             │
                                                             ▼
                                     Server EvidenceStore / Report / Mac Test Console
```

ZEGO 的对应目录是：

| 层 | ZEGO 范例 | 新 SDK 需要做什么 |
|---|---|---|
| Adapter Source | `sdk_adapters/zego/` | 新建 `sdk_adapters/<sdk>/` 四个声明文件 |
| 编译产物 | `sdk_registry/compiled/zego_express.json` | 由编译器生成并提交，不手写 |
| Python facade | `python_sdk/beacon_test/generated/zego_express.py` | 由 Registry 生成并提交，不手写 |
| Mac 原生实现 | `agents/mac/src/vendors/zego/rtc_backend_real_zego.mm` | 按供应商 SDK 建立独立 backend 与生命周期 |
| Mac bridge | `mac_zego_agent_bridge` | 增加该 vendor 的编译变体、loader、词表和 provider 注册 |
| 用例 | `test_cases/python/zego/zego_l1_cases.py`、`zego_video_cases.py` | 以 typed facade 书写真实可运行的 case |
| real gate | `scripts/validation/run_mac_zego_real.py` | 构建、启动 Agent、等待注册并执行真实 case |

## 1. 下载 SDK，并把密钥留在本地环境

把 Framework/XCFramework 放到开发机本地路径，并在被忽略的本地 env 文件中提供 SDK 根目录、App ID、签名和测试用户 token。ZEGO 的真实 gate 使用：

```text
ZEGO_MAC_SDK_ROOT
ZEGO_APP_ID
ZEGO_APP_SIGN
ZEGO_USER1_ID / ZEGO_USER1_TOKEN
ZEGO_USER2_ID / ZEGO_USER2_TOKEN
```

新 SDK 可以使用不同名称，但应把“运行时所需环境变量”和“缺失时的 skipped 语义”写进对应 real gate。不得把 App Sign、token、私有下载 URL 或绝对本机路径写入 source、报告和文档示例。

ZEGO 的 `framework_slice()` 会从 `ZegoExpressEngine.xcframework` 选择当前 macOS slice；CMake 只在 `BEACON_ENABLE_ZEGO_REAL=ON` 时链接该 Framework。其他 SDK 同样应把 SDK 探测、链接和运行期 loader path 限在自己的变体中。

## 2. 声明 SDK Registry Source

新建目录：

```text
sdk_adapters/<sdk>/
  capabilities.yaml
  mappings.yaml
  evidence.yaml
  providers.yaml
```

四个文件各有一个所有权，不要把它们合并成一个“方便维护”的大文件：

| 文件 | 回答的问题 |
|---|---|
| `capabilities.yaml` | 这个 SDK 可被独立验证的能力是什么？ |
| `mappings.yaml` | 能力对应哪些原生调用、回调、参数 schema 和回调可过滤字段？ |
| `evidence.yaml` | 每项能力运行后应产生哪些 Evidence？ |
| `providers.yaml` | 哪个平台的哪个 provider 真正支持这些 interface/function？ |

以 ZEGO 的登录能力为例，`room_login` 声明 `ZegoExpressEngine.loginRoom`，并在 `room_state_observability` 声明 `ZegoEventHandler.onRoomStateUpdate`。这两个能力刻意分开：前者是调用面，后者才是“登录已经被 SDK 接受”的可观测事实。

`mappings.yaml` 中的 `params_schema`、callback `payload_schema` 和 `filterable_fields` 是运行期合同。Python 用例只能在 `match={...}` 中使用已声明的可过滤字段；因此不要凭 SDK 文档猜测字段名，必须以实际回调 payload 验证后再加入声明。

`providers.yaml` 也不是说明文字。ZEGO 把 `zego_engine`、`zego_room`、`zego_preview`、`zego_publisher`、`zego_player` 声明给 `ZegoRTCInvocationProvider`，把 `zego_visual_probe` 声明给 `ZegoVisualProbeProvider`。当一个 target 在 macOS 没有 `supported` provider 映射时，Server 会在转发前判定为 `unsupported`，而不是等 Agent 返回一个模糊的 unknown invocation。

## 3. 编译声明，生成 facade 和 callback 词表

Adapter source 写完后，先运行：

```bash
make sdk-facade
make sdk-facade-check
make sdk-native-vocabulary
make test-protocol
```

这一步应产出并校验：

- `sdk_registry/compiled/<sdk>.json`：Server、CI 与编排读取的唯一 SDK 描述；
- `python_sdk/beacon_test/generated/<sdk>.py`：测试作者使用的 typed facade；
- `agents/mac/src/generated/rtc_event_targets_<vendor>.h`：该 vendor 的 callback target 词表。

不要手改 generated 文件来让编译通过。应该修正 source 声明或生成器合同；`--check` 的目的就是阻止 source、artifact、facade 和原生词表漂移。

## 4. 增加 macOS vendor 编译变体

真实 SDK 不应塞进已有厂商 binary。新增 SDK 时，需要一个独立 build variant，例如 ZEGO 的 `mac_zego_agent_bridge`。它至少包含以下职责：

1. **SDK loader**：加载、配置和释放自己的 Framework；只理解本供应商的 App ID/签名配置。
2. **原生 backend**：把 Beacon provider 调用翻译成 SDK 原生调用，维护该 SDK 的资源和线程规则。
3. **invocation provider**：只注册声明为 macOS supported 的 interface/function。
4. **event bridge**：把原生 delegate/event handler 回调转换为声明过的 Callback Target 和 Evidence。
5. **可视化 provider（按需）**：画面绑定和本地视图快照属于 Beacon 的验证能力，不等同于供应商的远端截图 API。

ZEGO 的 backend 在 `rtc_backend_real_zego.mm` 中使用 `ZegoCanvas` 绑定预览与远端流；收到 `onPlayerRenderVideoFirstFrame` 后才把远端渲染视为已观察。它通过 AppKit 对已绑定的 `NSView` 生成 JPEG，并发送 `BeaconZegoVisualProbe.onRenderedViewSnapshot`。这证明的是本机渲染视图的 artifact，不应在报告中表述为“远端用户截图”。

原生生命周期也必须按供应商语义实现。ZEGO 是创建 engine、登录房间、预览/发布/播放、停止播放和发布、停止预览、释放 view、登出、销毁 engine；新 SDK 若要求先收到离开回调再销毁房间，必须保持那个顺序，不能为了统一接口而改写。

## 5. 用 Python Test Source 表达测试意图

新增 case 只写在 `test_cases/python/`，使用生成的 facade，不直接构造 protocol packet，也不手写 node ID。

下面使用当前 ZEGO facade 表达登录与回调验证。完整 metadata 和可运行实现见 [ZEGO L1 用例](../test_cases/python/zego/zego_l1_cases.py)。

```python
from beacon_test import BeaconSession


def test_zego_login_callback(session: BeaconSession) -> None:
    sdk = session.device("primary").zego_express
    engine, room = sdk.zego_engine, sdk.zego_room
    assert engine.create_engine_with_profile().code == 0
    try:
        assert room.login_room(
            room_id="smoke", user_id="user-1", token="{{ZEGO_USER1_TOKEN}}"
        ).code == 0
        room.on_room_state_update.wait(
            match={"room_id": "smoke", "state": 2, "error_code": 0}, timeout_s=5
        )
    finally:
        try:
            assert room.logout_room().code == 0
        finally:
            assert engine.destroy_engine().code == 0
```

用例通过 `@beacon_test` 声明 catalog metadata，Runner 注入 `BeaconSession`。每次 facade 调用即时执行，普通 Python `assert` 判断结果，`try/finally` 负责清理；不再使用 `ctx.step` 或 `cleanup_step`。这里的 `state=2` 是 ZEGO 范例的值，新 SDK 必须使用其真实回调和经过验证的成功条件。token 保持占位符，由 real gate 在运行时填入。

双端 1V1 用例用 `devices=["primary", "peer"]` 声明角色，Server 按 Agent tag 的 `role:primary` / `role:peer` 选择设备。ZEGO 画面 case 按以下次序组织：两端创建与登录 → 本地预览 → 各自发布 stream → 订阅对端 stream → 等待远端首帧 → 观察窗口 → 截取两端远端视图 → 逆序 cleanup。每一步有独立的 Evidence 或 call assertion，失败时报告能定位到设备角色和动作，而不是只剩“1V1 failed”。

更多作者规则见 [Python Test Authoring Guide](python-test-authoring-guide.md)。

## 6. 写 real gate：进程、注册和凭证边界

真实 gate 的职责不是模拟 SDK，而是管理可重复的本机运行拓扑：

1. 检查 SDK Framework 和本地环境变量；缺失时写 `skipped` artifact 并返回 0。
2. 配置仅该 vendor 的 CMake 变体并构建 native Agent。
3. 启动 Beacon Server，启动一台或多台 direct WebSocket Agent。
4. 等待每个 Agent 出现在 `/api/v1/devices`，再提交 case。
5. 无论成功或失败，终止 Agent 并关闭 Server。

`scripts/validation/run_mac_zego_real.py` 是这个模式的参考：两个 Agent 使用同一 group，并分别带 `role:primary`、`role:peer` tag；用例只引用角色，不感知 node ID。它用独立的 `ZEGO_USER1_TOKEN`、`ZEGO_USER2_TOKEN` 登录同一个房间，避免把“同 token 的双端偶然可运行”误判为真实 1V1 支持。

建议先建立 L1 gate，再增加媒体 gate。ZEGO 的入口是：

```bash
make test-mac-zego-real
```

环境齐备时，构建、Agent 注册、回调、首帧、快照或 assertion 失败都应使命令非零；环境缺失才是可解释的 `skipped`。

## 7. 接入 Mac Test Console

Console 不是另一套执行系统。它读取 Server 的 catalog 和 report，并通过 SDK route 选择默认 Agent；真正的调用、Evidence 和判定仍走同一条 Server/Agent 主链。

要让一个新 macOS SDK 出现在 Console，需要满足：

- adapter artifact 声明的 case 的 `platform` 为 `mac`；
- case 是 `runnable`，并且有该 SDK 的真实 Agent；
- Console 的 SDK catalog 允许该 SDK；
- 统一 real server 启动器注册该 SDK 的 primary/peer Agent，并为 Console 配置 `<sdk>=<server-url>#<primary-node-id>` route；
- 同一个统一 Server 上的本地 env 使用相同 `BEACON_AUTH_TOKEN`。

现有三 SDK 的人工入口是：

```bash
# Terminal 1：统一 Server 与 15 个真实 Agent
make run-mac-console-real-server

# Terminal 2：启动 Mac Test Console
make run-mac-console-app
```

在 Console 中选择新 SDK 的 suite 和 case。ZEGO 的代表用例是 `TC-PY-ZEGO-L1-1V1-VIDEO-RENDER-SNAPSHOT`；结果页应显示调用与回调的执行记录、用例终态和报告里的 artifact 引用。不要因为 Console 已连接就宣称媒体已验证；必须实际运行画面 case 并检查首帧、快照和 cleanup 结果。

统一 Server 方便开发者在一个 App 中选择 SDK，但不意味着不同 SDK 的 native lifecycle 被合并。每个 Agent 仍是自己的 vendor binary，分别链接自己的媒体 Framework。

## 8. 验收顺序

按下面顺序推进，能把“声明错误”“bridge 没注册”“真实 SDK 行为错误”分层定位：

| 阶段 | 命令或检查 | 通过意味着什么 |
|---|---|---|
| 声明 | `make sdk-facade-check`、`make sdk-native-vocabulary` | Source、artifact、facade、callback 词表没有漂移 |
| 协议 | `make test-protocol` | Python source 可被导出，schema/target/过滤字段合法 |
| mock（若有） | `make test-mac-mock`、`make test-e2e-mock` | provider dispatch 和基础协议链可工作；不证明真实 SDK |
| vendor real | `make test-mac-<vendor>-real` | 本机 Framework、Agent、凭证、原生回调和目标场景成立 |
| Console manual | `make run-mac-console-real-server` + `make run-mac-console-app` | 开发者可在真实 App 中看到并下发该 SDK case |
| Console aggregate | `make test-mac-console-real` | 多个 vendor 在同一 Server/Console 拓扑中共存；不替代各 vendor 的深度 gate |

画面场景按 [证据与结果规则](development.md#结果与证据)验证：运行时缺少必需画面 Evidence 必须失败。尚未实现的场景单独说明，不能记为已通过。

## 常见误区

| 误区 | 正确处理 |
|---|---|
| 在 Server 加 `if sdk == "new_sdk"` | 把 SDK 知识放在 adapter source、provider 和 vendor bridge；Server 只读 artifact。 |
| 复用另一家 RTC 的 room/channel、UID 或 callback 名称 | 以新 SDK 的对象模型命名 capability/interface/target，保持 native lifecycle。 |
| 只断言 API 返回 `0` | 断言原生 callback、state、metric 或 artifact；调用成功只是开始。 |
| 把 SDK log 当作通过条件 | log 用于诊断；优先用 event/state/metric/artifact Evidence。 |
| 缺 SDK 或 token 时仍报 passed | 真实 gate 写正式 `skipped` artifact；不能假绿。 |
| 只在 Console 中看到 case 就认为已完成 | 运行 real case，检查 Agent 注册、逐步 Evidence、artifact 和 cleanup。 |
| 把本地渲染 view JPEG 叫作远端截图 | 明确它是 Beacon 在本机已绑定 view 上采集的本地 artifact。 |

## 提交前清单

- [ ] 新 SDK 只有自己的 adapter source、Framework loader、Mac build variant、provider 和 callback vocabulary。
- [ ] `capabilities.yaml`、`mappings.yaml`、`evidence.yaml`、`providers.yaml` 均已声明且通过编译。
- [ ] generated registry、typed facade、vendor callback header 已更新，且生成检查无 drift。
- [ ] Python case 使用 typed facade、设备角色和 `try/finally`；没有真实凭证或裸 protocol packet。
- [ ] real gate 对“环境缺失”和“运行失败”有不同、可审计的结果。
- [ ] 真实 case 至少覆盖一个原生成功回调；媒体 case 额外覆盖首帧、artifact 与 cleanup。
- [ ] Console 能发现该 SDK 的真实 Agent，并能运行同一份 case。
- [ ] `git diff --check` 和本次变更适用的验证命令通过。

相关说明：[架构边界与回调机制](architecture.md)、[开发与验证](development.md)。
