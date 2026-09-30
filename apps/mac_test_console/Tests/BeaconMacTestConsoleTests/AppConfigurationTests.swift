import XCTest
@testable import BeaconMacTestConsole

final class AppConfigurationTests: XCTestCase {
    func testReadsConsoleConfigurationFromEnvironment() {
        let config = AppConfiguration(
            arguments: ["BeaconMacTestConsole"],
            environment: [
                "BEACON_CONSOLE_SERVER_URL": "http://127.0.0.1:9001",
                "BEACON_AUTH_TOKEN": "local-token",
                "BEACON_NODE_ID": "mac-real-e2e-001",
                "BEACON_CONSOLE_SDK_ROUTES": "agora_rtc=http://127.0.0.1:9001#mac-agora,volcengine_rtc=http://127.0.0.1:9002",
                "BEACON_CONSOLE_AUTORUN_PREFIX": "TC-MAC-AGORA-REAL",
                "BEACON_CONSOLE_AUTORUN_CASE_IDS": "TC-1,TC-2",
                "BEACON_CONSOLE_AUTORUN_OUTPUT": "/tmp/beacon-autorun.json",
            ]
        )

        XCTAssertEqual(config.serverURL.absoluteString, "http://127.0.0.1:9001")
        XCTAssertEqual(config.token, "local-token")
        XCTAssertEqual(config.nodeID, "mac-real-e2e-001")
        XCTAssertEqual(
            config.sdkRoutes,
            [
                "agora_rtc": SDKRoute(url: URL(string: "http://127.0.0.1:9001")!, nodeID: "mac-agora"),
                "volcengine_rtc": SDKRoute(url: URL(string: "http://127.0.0.1:9002")!, nodeID: nil),
            ]
        )
        XCTAssertEqual(config.autorunPrefix, "TC-MAC-AGORA-REAL")
        XCTAssertEqual(config.autorunCaseIDs, ["TC-1", "TC-2"])
        XCTAssertEqual(config.autorunOutputPath, "/tmp/beacon-autorun.json")
    }

    func testCommandLineArgumentsOverrideEnvironmentAndTrimAutorunCaseIDs() {
        let config = AppConfiguration(
            arguments: [
                "BeaconMacTestConsole",
                "--server-url", "http://127.0.0.1:9100",
                "--token", "cli-token",
                "--node-id", "mac-cli",
                "--sdk-routes", "volcengine_rtc=http://127.0.0.1:9101",
                "--autorun-prefix", "TC-MAC-CLI",
                "--autorun-case-ids", " TC-2, ,TC-1 ",
                "--autorun-output", "/tmp/cli-output.json",
            ],
            environment: [
                "BEACON_CONSOLE_SERVER_URL": "http://127.0.0.1:9001",
                "BEACON_AUTH_TOKEN": "env-token",
                "BEACON_NODE_ID": "mac-env",
                "BEACON_CONSOLE_SDK_ROUTES": "agora_rtc=http://127.0.0.1:9001",
                "BEACON_CONSOLE_AUTORUN_PREFIX": "TC-MAC-ENV",
                "BEACON_CONSOLE_AUTORUN_CASE_IDS": "TC-ENV",
                "BEACON_CONSOLE_AUTORUN_OUTPUT": "/tmp/env-output.json",
            ]
        )

        XCTAssertEqual(config.serverURL.absoluteString, "http://127.0.0.1:9100")
        XCTAssertEqual(config.token, "cli-token")
        XCTAssertEqual(config.nodeID, "mac-cli")
        XCTAssertEqual(config.sdkRoutes, ["volcengine_rtc": SDKRoute(url: URL(string: "http://127.0.0.1:9101")!, nodeID: nil)])
        XCTAssertEqual(config.autorunPrefix, "TC-MAC-CLI")
        XCTAssertEqual(config.autorunCaseIDs, ["TC-2", "TC-1"])
        XCTAssertEqual(config.autorunOutputPath, "/tmp/cli-output.json")
    }

    func testSDKRoutesSkipMalformedEntries() {
        let config = AppConfiguration(
            arguments: ["BeaconMacTestConsole"],
            environment: [
                "BEACON_CONSOLE_SDK_ROUTES": "agora_rtc,=http://127.0.0.1:9001,volcengine_rtc=, mock_echo = http://127.0.0.1:9002 # node-1 ,,",
            ]
        )

        XCTAssertEqual(
            config.sdkRoutes,
            ["mock_echo": SDKRoute(url: URL(string: "http://127.0.0.1:9002")!, nodeID: "node-1")]
        )
    }

    func testEmptyConfigurationUsesDefaultsAndNoAutorun() {
        let config = AppConfiguration(arguments: ["BeaconMacTestConsole"], environment: [:])

        XCTAssertEqual(config.serverURL.absoluteString, "http://127.0.0.1:8000")
        XCTAssertEqual(config.token, "")
        XCTAssertNil(config.nodeID)
        XCTAssertEqual(config.sdkRoutes, [:])
        XCTAssertNil(config.autorunPrefix)
        XCTAssertNil(config.autorunCaseIDs)
        XCTAssertNil(config.autorunOutputPath)
    }

    @MainActor
    func testAppStateCopiesConfigurationAndInitialConnectionStatus() {
        let config = AppConfiguration(
            arguments: [
                "BeaconMacTestConsole",
                "--server-url", "http://127.0.0.1:9100",
                "--token", "cli-token",
                "--node-id", "mac-cli",
                "--sdk-routes", "agora_rtc=http://127.0.0.1:9100#mac-cli",
                "--autorun-prefix", "TC-MAC-CLI",
                "--autorun-case-ids", "TC-1",
                "--autorun-output", "/tmp/cli-output.json",
            ],
            environment: [:]
        )

        let state = AppState(configuration: config, connectionStatus: .connected(version: "0.1.0-p0"))

        XCTAssertEqual(state.serverURL.absoluteString, "http://127.0.0.1:9100")
        XCTAssertEqual(state.token, "cli-token")
        XCTAssertEqual(state.selectedNodeID, "mac-cli")
        XCTAssertEqual(state.sdkRoutes, ["agora_rtc": SDKRoute(url: URL(string: "http://127.0.0.1:9100")!, nodeID: "mac-cli")])
        XCTAssertEqual(state.autorunPrefix, "TC-MAC-CLI")
        XCTAssertEqual(state.autorunCaseIDs, ["TC-1"])
        XCTAssertEqual(state.autorunOutputPath, "/tmp/cli-output.json")
        XCTAssertEqual(state.connectionStatus, .connected(version: "0.1.0-p0"))
    }
}
