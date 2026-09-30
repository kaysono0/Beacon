# Python Test Authoring Guide

正式用例写在 `test_cases/python/`，由 `@beacon_test` 声明静态 catalog metadata，并由独立 Runner 进程注入同步 `BeaconSession`。参考当前可运行的 [Agora 双端用例](../test_cases/python/agora/agora_bidirectional_video_cases.py)和 [callback 后续操作用例](../test_cases/python/agora/agora_legacy_cleanup_cases.py)。

诊断与 direct-agent 验证同样把最小动作写成正式 case，再通过 `/api/v1/test-runs` 执行。`BeaconSession` 由 Runner 注入；作者不自行构造 run token，不使用独立 Client、动态 `.sdk()` 或旧 SDK HTTP API。

## 最小用例

```python
from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-EXAMPLE-ECHO",
    name="Echo once",
    platform="common",
    suite="example",
    scenario_family="echo_basic",
    implementation_status="runnable",
    covered_capabilities=["echo_basic"],
    sdk_names=["mock_echo"],
)
def test_echo(session: BeaconSession) -> None:
    result = session.device("primary").mock_echo.echo.echo(message="hello")
    assert result.code == 0
```

一行 generated facade 调用会立即发出一个 HTTP call，Server 按当前 run 的 role/node/lease 绑定验证并下发至 Agent，返回 `CallResult` 后 Python 才执行下一行。`CallResult` 包含 `code`、`value`、`operation_id` 等字段；默认 `check=True`，Native 非零结果会抛出 `NativeCallError`。测试预期失败时使用该方法的 `check=False`，并断言具体结果。没有 `ctx.step`、调用录制或第二次执行阶段。

## Callback 与 Observation

```python
engine = session.device("primary").agora.rtc_engine
assert engine.join_channel(channel="room", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
observed = engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
assert observed.payload["uid"] == 1001
```

Callback 作为独立 Observation 保存；`wait`/`query` 按当前 case、role、node 和 lease 查询，不推断它属于某次 call。需要限定新事实时传 `after_cursor`。可查询的 callback 字段以 SDK Registry 声明为准。普通 Python `assert` 决定 case 结果，报告从 case 终态和 Observation 生成。

需要在 SDK callback 内执行后续动作时，先注册 SDK 或 Native 层暴露的 target，再调用触发 callback 的接口：

```python
registration = session.register_callback(
    role="primary",
    event_target={"sdk": "agora_rtc", "interface": "rtc_engine", "class": "AgoraRtcEngineDelegate", "function": "onJoinChannelSuccess"},
    calls=[{"target": {"sdk": "beacon_system", "interface": "clock", "class": "SystemClock", "function": "waitInMs"}, "params": {"ms": 1}}],
)
assert registration.code == 0
# 随后调用 engine.join_channel(...)，再等待 on_join_channel_success。
# 在返回的 Observation.callback_execution 中检查 defer_matched、defer_executed 和 call_results。
```

注册的后续动作由 Agent 在 Native callback 中匹配并执行，Python 不跨进程注册 callback 函数。实际代码和结果断言见 `TC-MAC-AGORA-REAL-JOIN-CALLBACK`。

## 多设备、资源和清理

声明 `devices=["primary", "peer"]` 后，用 `session.device(role)` 分别获取两个角色的 facade。按 Python 顺序调用和等待；每次 call 有独立 `operation_id`。资源使用 `CallResult.resource` 与后续调用的 `resource=` 参数传递，并受 run/case/role scope 约束。需要 Native 失败返回时使用 `check=False`；需要清理时使用 `try/finally`，使前序断言失败后仍执行 cleanup。

视频证据用 vendor facade 的 `visual_probe.bind_local_video` / `bind_remote_video`、`capture_snapshot` 和对应的 `on_snapshot_taken.wait`。作者只传逻辑 `view_role`；真实画面和声音仍需按 [视觉证据标准](development.md#结果与证据)验收，不能从一次 callback 或静态快照推断主观视听通过。

## 目录与验证

- `test_cases/python/`：唯一正式作者源。
- `python_sdk/beacon_test/generated/`：由 SDK Registry 生成的 typed facade；修改 Registry 或生成器后运行 `make sdk-facade-check`。
- `test_cases/legacy_yaml_archive/`：历史审计材料，不进入生产 Runner。
- `reports/latest/compiled-test-cases/`：`make test-protocol` 的诊断导出，不是运行输入。

修改用例后，按 [CI 验证合同](development.md)运行适用的 `make test-protocol`、`make test-server-quiet`、`make test-e2e-mock` 和相关真实 Vendor gate。Mock 通过不替代真实 SDK callback 或媒体证据。
