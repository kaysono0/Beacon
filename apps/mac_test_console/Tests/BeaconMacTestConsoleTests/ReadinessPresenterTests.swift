import XCTest
import SwiftUI
@testable import BeaconMacTestConsole

final class ReadinessPresenterTests: XCTestCase {
    func testServerSectionDistinguishesHealthyDegradedUnreachableAndUnchecked() {
        let healthy = ReadinessSnapshot(
            serverStatus: StatusResponse(service: "beacon-server", status: "ok", version: "0.1.0-p0")
        )
        let section = ReadinessPresenter.serverSection(of: healthy)
        XCTAssertEqual(section.level, .ready)
        XCTAssertEqual(section.summary, "beacon-server 0.1.0-p0 · ok")
        XCTAssertNil(section.errorText)

        // server 进程在但状态异常：属于「能连上有缺口」，不是读不到。
        let degraded = ReadinessSnapshot(
            serverStatus: StatusResponse(service: "beacon-server", status: "degraded", version: "0.1.0-p0")
        )
        XCTAssertEqual(ReadinessPresenter.serverSection(of: degraded).level, .attention)

        let unreachable = ReadinessSnapshot(serverError: "HTTP 500: server request failed")
        let unavailable = ReadinessPresenter.serverSection(of: unreachable)
        XCTAssertEqual(unavailable.level, .unavailable)
        XCTAssertEqual(unavailable.summary, "Unavailable")
        XCTAssertEqual(unavailable.errorText, "HTTP 500: server request failed")

        // 面板刚打开、还没拉过时既没有事实也没有错误，文案必须与失败区分开。
        let unchecked = ReadinessPresenter.serverSection(of: ReadinessSnapshot())
        XCTAssertEqual(unchecked.level, .unavailable)
        XCTAssertEqual(unchecked.summary, "Not checked")
        XCTAssertNil(unchecked.errorText)
    }

    func testAgentsSectionSeparatesEmptyPoolOfflineAgentAndRequestFailure() {
        // 没有在线 Agent 时 run 会选不到设备，必须在开跑前可见。
        let empty = ReadinessPresenter.agentsSection(of: ReadinessSnapshot())
        XCTAssertEqual(empty.level, .attention)
        XCTAssertEqual(empty.summary, "No agent online")

        let oneOnline = ReadinessSnapshot(devices: [device(nodeID: "mac-1", status: "online")])
        let readySection = ReadinessPresenter.agentsSection(of: oneOnline)
        XCTAssertEqual(readySection.level, .ready)
        XCTAssertEqual(readySection.summary, "1 agent online")

        let mixed = ReadinessSnapshot(devices: [
            device(nodeID: "mac-1", status: "online"),
            device(nodeID: "mac-2", status: "offline"),
        ])
        let attention = ReadinessPresenter.agentsSection(of: mixed)
        XCTAssertEqual(attention.level, .attention)
        XCTAssertEqual(attention.summary, "2 agents registered, 1 agent not online")

        let failed = ReadinessSnapshot(devicesError: "HTTP 401: auth token is missing or invalid")
        let unavailable = ReadinessPresenter.agentsSection(of: failed)
        XCTAssertEqual(unavailable.level, .unavailable)
        XCTAssertEqual(unavailable.errorText, "HTTP 401: auth token is missing or invalid")
    }

    func testCapabilitiesSectionCountsSDKsAndMethods() {
        let empty = ReadinessPresenter.capabilitiesSection(of: ReadinessSnapshot())
        XCTAssertEqual(empty.level, .attention)
        XCTAssertEqual(empty.summary, "No SDK capability loaded")

        let loaded = ReadinessSnapshot(sdkCapabilities: [
            sdk(named: "agora_rtc", interfaces: 2, methods: 3, callbacks: 1),
            sdk(named: "mock_complex_sdk", interfaces: 1, methods: 1, callbacks: 0),
        ])
        let section = ReadinessPresenter.capabilitiesSection(of: loaded)
        XCTAssertEqual(section.level, .ready)
        XCTAssertEqual(section.summary, "2 SDKs · 4 methods")

        let failed = ReadinessSnapshot(capabilitiesError: "HTTP 401: auth token is missing or invalid")
        XCTAssertEqual(ReadinessPresenter.capabilitiesSection(of: failed).level, .unavailable)
    }

    func testCapabilitySummaryKeepsSingularAndPluralReadable() {
        XCTAssertEqual(
            ReadinessPresenter.capabilitySummary(of: sdk(named: "agora_rtc", interfaces: 1, methods: 1, callbacks: 1)),
            "1 interface · 1 method · 1 callback"
        )
        XCTAssertEqual(
            ReadinessPresenter.capabilitySummary(of: sdk(named: "agora_rtc", interfaces: 2, methods: 5, callbacks: 0)),
            "2 interfaces · 5 methods · 0 callbacks"
        )
    }

    func testLastSeenTextCoversSecondMinuteAndHourScales() {
        let now = Date(timeIntervalSince1970: 1_700_000_100)
        XCTAssertEqual(ReadinessPresenter.lastSeenText(milliseconds: 1_700_000_099_000, now: now), "just now")
        XCTAssertEqual(ReadinessPresenter.lastSeenText(milliseconds: 1_700_000_070_000, now: now), "30s ago")
        XCTAssertEqual(ReadinessPresenter.lastSeenText(milliseconds: 1_699_999_980_000, now: now), "2m ago")
        XCTAssertEqual(ReadinessPresenter.lastSeenText(milliseconds: 1_699_992_900_000, now: now), "2h ago")
        // Agent 时钟超前时不显示负数，归入 just now。
        XCTAssertEqual(ReadinessPresenter.lastSeenText(milliseconds: 1_700_000_200_000, now: now), "just now")
    }

    func testLevelSymbolAndColorFollowExistingRunStatusVocabulary() {
        XCTAssertEqual(ReadinessPresenter.symbolName(for: .ready), "checkmark.circle.fill")
        XCTAssertEqual(ReadinessPresenter.symbolName(for: .attention), "exclamationmark.triangle.fill")
        XCTAssertEqual(ReadinessPresenter.symbolName(for: .unavailable), "xmark.circle.fill")
        XCTAssertEqual(ReadinessPresenter.color(for: .ready), .green)
        XCTAssertEqual(ReadinessPresenter.color(for: .attention), .yellow)
        XCTAssertEqual(ReadinessPresenter.color(for: .unavailable), .red)
    }

    func testSectionAccessibilityKeyDerivesFromTitle() {
        let section = ReadinessPresenter.capabilitiesSection(of: ReadinessSnapshot())
        XCTAssertEqual(section.id, "SDK capabilities")
        XCTAssertEqual(section.accessibilityKey, "sdk_capabilities")
        XCTAssertEqual(ReadinessPresenter.serverSection(of: ReadinessSnapshot()).accessibilityKey, "server")
    }

    private func device(nodeID: String, status: String) -> DeviceSummary {
        DeviceSummary(nodeID: nodeID, platform: "macos", status: status, lastSeenMs: 1_700_000_000_000)
    }

    /// 用重复的空 target 表达计数，避免测试再手抄一遍 registry 形状。
    private func sdk(named name: String, interfaces: Int, methods: Int, callbacks: Int) -> SDKCapability {
        let methodTargets = (0..<methods).map { index in
            Target(sdk: name, interface: nil, className: "Engine", function: "method\(index)")
        }
        let callbackTargets = (0..<callbacks).map { index in
            CallbackCapability(
                target: Target(sdk: name, interface: nil, className: "Engine", function: "onEvent\(index)"),
                filterableFields: [],
                evidenceSummaryFields: []
            )
        }
        // 方法数按 SDK 汇总，因此放在单个 interface 上与分散在多个 interface 上等价。
        let sdkInterface = SDKInterfaceCapability(
            interface: "core",
            methods: methodTargets,
            callbacks: callbackTargets,
            metrics: [],
            states: []
        )
        let filler = (1..<interfaces).map { index in
            SDKInterfaceCapability(interface: "extra\(index)", methods: [], callbacks: [], metrics: [], states: [])
        }
        return SDKCapability(sdk: name, interfaces: [sdkInterface] + filler)
    }
}
