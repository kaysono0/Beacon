import XCTest
@testable import BeaconMacTestConsole

final class ModelsTests: XCTestCase {
    func testJSONValueDecodesDisplaysAndEncodesConsolePayloadShapes() throws {
        let data = Data(
            #"""
            {
              "string": "join ok",
              "int": 17,
              "double": 1.5,
              "bool": true,
              "object": {"channel": "real-smoke", "uid": 1001},
              "array": ["step_started", 3],
              "null": null
            }
            """#.utf8
        )

        let values = try JSONDecoder.beacon.decode([String: JSONValue].self, from: data)

        XCTAssertEqual(values["string"]?.stringValue, "join ok")
        XCTAssertEqual(values["int"]?.stringValue, "17")
        XCTAssertEqual(values["double"]?.stringValue, "1.5")
        XCTAssertEqual(values["bool"]?.stringValue, "true")
        XCTAssertNil(values["object"]?.stringValue)
        XCTAssertNil(values["array"]?.stringValue)
        XCTAssertNil(values["null"]?.stringValue)
        XCTAssertEqual(values["int"]?.intValue, 17)
        XCTAssertNil(values["string"]?.intValue)
        XCTAssertEqual(values["object"]?.displayValue, "{channel,uid}")
        XCTAssertEqual(values["array"]?.displayValue, "[2]")
        XCTAssertEqual(values["null"]?.displayValue, "")

        let encoded = try JSONEncoder.beacon.encode(values)
        let roundTrip = try JSONDecoder.beacon.decode([String: JSONValue].self, from: encoded)
        XCTAssertEqual(roundTrip, values)
    }

    func testModelIdentifiersAndComputedRunFieldsMatchConsoleContracts() {
        let sdk = SDKCapability(sdk: "agora_rtc", interfaces: [])
        let sdkInterface = SDKInterfaceCapability(interface: "rtc_engine", methods: [], callbacks: [], metrics: [], states: [])
        let testCase = TestCaseSummary(caseID: "TC-MAC-AGORA-REAL-JOIN-CALLBACK", name: "Join", platform: "mac", suite: "mac", tags: [])
        let passedRun = RunResponse(runID: "run-passed", status: "passed", stepResults: [])
        let cancelledRun = RunResponse(runID: "run-cancelled", status: "cancelled", stepResults: [])
        let runningRun = RunResponse(runID: "run-running", status: "running", stepResults: [])
        let zeroDuration = StepResultSummary(
            caseID: "TC-1",
            stepID: "step-1",
            status: "passed",
            error: nil,
            artifacts: [],
            durationMs: 0
        )
        let finishedHistory = RunHistorySummary(
            runID: "run-history-passed",
            status: "passed",
            caseIDs: ["TC-1"],
            createdAtMs: 100,
            finishedAtMs: 150,
            durationMs: 50
        )
        let openHistory = RunHistorySummary(
            runID: "run-history-running",
            status: "running",
            caseIDs: ["TC-1"],
            createdAtMs: 300,
            finishedAtMs: nil,
            durationMs: nil
        )

        XCTAssertEqual(sdk.id, "agora_rtc")
        XCTAssertEqual(sdkInterface.id, "rtc_engine")
        XCTAssertEqual(testCase.id, "TC-MAC-AGORA-REAL-JOIN-CALLBACK")
        XCTAssertTrue(passedRun.isTerminal)
        XCTAssertTrue(cancelledRun.isTerminal)
        XCTAssertFalse(runningRun.isTerminal)
        XCTAssertEqual(zeroDuration.id, "step-1")
        XCTAssertEqual(zeroDuration.code, 0)
        XCTAssertEqual(zeroDuration.message, "")
        XCTAssertEqual(zeroDuration.durationLabel, "")
        // 历史摘要与 RunResponse 共用同一套终态词汇，sheet 里的状态图标因此不会出现第三种判定。
        XCTAssertEqual(finishedHistory.id, "run-history-passed")
        XCTAssertTrue(finishedHistory.isTerminal)
        XCTAssertEqual(openHistory.id, "run-history-running")
        XCTAssertFalse(openHistory.isTerminal)
        XCTAssertNil(openHistory.durationMs)
    }

    func testDeviceSummaryDecodesReadinessFieldsAndIgnoresServerExtras() throws {
        let data = Data(
            #"""
            {"devices":[
              {"node_id":"mac-local-001","platform":"macos","group_id":"local","tags":["mock"],
               "capabilities":["rtc.mock"],"status":"online","last_seen_ms":1700000000000}
            ]}
            """#.utf8
        )

        let response = try JSONDecoder.beacon.decode(DevicesResponse.self, from: data)

        // 面板只声明四个字段；server 的 group_id/tags/capabilities 必须被安静忽略而不是解码失败。
        XCTAssertEqual(response.devices.count, 1)
        let device = try XCTUnwrap(response.devices.first)
        XCTAssertEqual(device.id, "mac-local-001")
        XCTAssertEqual(device.platform, "macos")
        XCTAssertEqual(device.status, "online")
        XCTAssertEqual(device.lastSeenMs, 1_700_000_000_000)
    }
}
