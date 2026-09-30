# Beacon 快速入门

先用 Mock 跑通执行链路，再用一个最小 Agora 用例验证真实 SDK callback 和清理。所有正式 Python 用例都由 Runner 注入同步 `BeaconSession`。

## 1. 跑通 Mock 链路

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。不需要真实 SDK 或凭证：

```bash
make test-e2e-mock
```

这个 gate 启动 Server 与 Mock Agent，执行正式 Python 用例，检查 call、callback Observation 与报告，结果写入 `reports/latest/report.json`。

## 2. 最小 Demo：等待回调与清理

将下面的完整用例保存为 `test_cases/python/agora/agora_quickstart_demo.py`：

```python
from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-QUICKSTART-JOIN-CALLBACK",
    name="Quickstart Agora join callback and cleanup",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_success_fact", "leave_cleanup"],
    token_bindings=[("quickstart-room", 1001)],
    sdk_names=["agora_rtc"],
)
def test_quickstart_agora_join_callback(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    try:
        result = engine.join_channel(
            channel="quickstart-room",
            uid=1001,
            token="{{AGORA_RTC_TOKEN}}",
        )
        assert result.code == 0

        observed = engine.on_join_channel_success.wait(
            match={"uid": 1001},
            timeout_s=5,
        )
        assert observed.payload["uid"] == 1001
    finally:
        assert engine.leave_channel().code == 0
```

`join_channel` 的返回值和 SDK callback 是两条独立事实：Demo 分别断言调用成功和 join callback 到达。`finally` 保证用例退出房间；Runner 还会在 case 前后执行 reset。`{{AGORA_RTC_TOKEN}}` 是运行时占位符；Server 根据 `token_bindings` 和本机 Agora App ID/Certificate 在启动时签发 token，不要把真实 token 写进用例。

## 3. 启动真实环境并运行 Demo

真实路径需要 macOS 13+、Xcode/Swift、CMake，以及 Agora、火山和 ZEGO 的 macOS SDK 与本机凭证。统一真实 Server 会启动三家 SDK 的 Agent，因此三家的配置都要齐全。可运行 `bash scripts/dev/setup_macos.sh --with-sdks` 准备开发工具并按提示下载 Agora 和火山 SDK；ZEGO SDK、凭证文件和完整字段要求见 [Mac Console 环境设置](mac-console.md)。本地配置写入 Git 忽略的 `local.agora.env` 和 `local.volcengine.env`，两份文件使用相同的 `BEACON_AUTH_TOKEN`。

先保存 Demo 文件，再分别在两个终端启动 Server 和 Mac Test Console。Server 启动时发现用例；之后新增或修改用例时，重启 Server 以刷新 catalog。

终端一：

```bash
make run-mac-console-real-server
```

终端二：

```bash
make run-mac-console-app
```

在 Mac Test Console 中选择 Agora，找到 `TC-MAC-AGORA-QUICKSTART-JOIN-CALLBACK` 并运行。运行记录中可以分别查看调用结果、join callback Observation 和 case 结果。结束后在终端一按 `Ctrl-C`，等待 Server 回收 Agent。

## 下一步

- [Python 用例编写指南](python-test-authoring-guide.md)：metadata、callback、资源和多设备。
- [Mac Console 操作指南](mac-console.md)：SDK 安装、凭证配置、Console 操作和真实验证入口。
- [架构概览](architecture.md)：Runner → BeaconSession → Server → Native。
- [开发与验证](development.md)：按改动范围选择验证 gate，Mock 不替代真实 SDK 验证。
- [新 SDK 接入指南](sdk-adapter-integration-guide.md)：为 Beacon 增加另一家 SDK 时参考。
