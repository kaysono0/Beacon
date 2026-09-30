import XCTest
@testable import BeaconMacTestConsole

final class ConnectionStatusTests: XCTestCase {
    func testResolvePrefersProbeFailureOverLoadFailure() {
        // 探活不通说明 server 不可达，目录加载的错误只是它的后果，不能盖掉根因。
        XCTAssertEqual(
            ConnectionStatus.resolve(probe: .unreachable(message: "connection refused"), load: .failed(message: "HTTP 401")),
            .failed(message: "connection refused")
        )
    }

    func testResolveSurfacesLoadFailureWhenServerIsReachable() {
        // status 端点无鉴权，token 错误时探活仍成功，失败必须由加载结果给出。
        XCTAssertEqual(
            ConnectionStatus.resolve(
                probe: .reachable(version: "0.1.0-p0"),
                load: .failed(message: "HTTP 401: auth token is missing or invalid")
            ),
            .failed(message: "HTTP 401: auth token is missing or invalid")
        )
    }

    func testResolveReportsConnectedWithServerVersion() {
        XCTAssertEqual(
            ConnectionStatus.resolve(probe: .reachable(version: "0.1.0-p0"), load: .loaded(caseCount: 41)),
            .connected(version: "0.1.0-p0")
        )
    }

    @MainActor
    func testAppStateStartsDisconnectedAndMovesThroughConnecting() {
        let state = AppState(configuration: AppConfiguration(arguments: ["BeaconMacTestConsole"], environment: [:]))

        XCTAssertEqual(state.connectionStatus, .disconnected)

        state.beginConnecting()
        XCTAssertEqual(state.connectionStatus, .connecting)
    }

    @MainActor
    func testAppStateApplyConnectionOverwritesPreviousConclusion() {
        let state = AppState(configuration: AppConfiguration(arguments: ["BeaconMacTestConsole"], environment: [:]))

        state.applyConnection(probe: .reachable(version: "0.1.0-p0"), load: .loaded(caseCount: 3))
        XCTAssertEqual(state.connectionStatus, .connected(version: "0.1.0-p0"))

        // 上一次 connected 不得在新一轮刷新失败后继续冒充当前事实。
        state.beginConnecting()
        state.applyConnection(probe: .unreachable(message: "connection refused"), load: .failed(message: "HTTP 401"))
        XCTAssertEqual(state.connectionStatus, .failed(message: "connection refused"))

        state.beginConnecting()
        state.applyConnection(probe: .reachable(version: "0.2.0"), load: .loaded(caseCount: 0))
        XCTAssertEqual(state.connectionStatus, .connected(version: "0.2.0"))
    }

    @MainActor
    func testAppStateApplyProbeOnlyNeverUpgradesToConnected() {
        let state = AppState(configuration: AppConfiguration(arguments: ["BeaconMacTestConsole"], environment: [:]))

        // 探活端点无鉴权：token 改错后 server 仍可达，旧结论必须原样保留，不能变绿。
        state.applyProbeOnly(probe: .reachable(version: "0.1.0-p0"), previous: .failed(message: "HTTP 401"))
        XCTAssertEqual(state.connectionStatus, .failed(message: "HTTP 401"))

        state.applyProbeOnly(probe: .reachable(version: "0.1.0-p0"), previous: .disconnected)
        XCTAssertEqual(state.connectionStatus, .disconnected)

        state.applyProbeOnly(probe: .unreachable(message: "connection refused"), previous: .connected(version: "0.1.0-p0"))
        XCTAssertEqual(state.connectionStatus, .failed(message: "connection refused"))
    }
}
