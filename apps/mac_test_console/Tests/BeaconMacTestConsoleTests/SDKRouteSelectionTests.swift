import Foundation
import XCTest
@testable import BeaconMacTestConsole

final class SDKRouteSelectionTests: XCTestCase {
    func testDoesNotOverwriteSDKSelectionWhenRoutesShareOneServer() {
        let serverURL = URL(string: "http://127.0.0.1:8000")!
        let capabilities = [
            SDKCapability(sdk: "agora_rtc", interfaces: []),
            SDKCapability(sdk: "volcengine_rtc", interfaces: []),
            SDKCapability(sdk: "zego_express", interfaces: []),
        ]
        let routes = Dictionary(uniqueKeysWithValues: capabilities.map {
            ($0.sdk, SDKRoute(url: serverURL, nodeID: "node-\($0.sdk)"))
        })

        XCTAssertNil(
            SDKRouteSelection.automaticallyAlignedSDK(
                capabilities: capabilities, routes: routes, serverURL: serverURL
            )
        )
    }

    func testAlignsSDKWhenOnlyOneRouteUsesCurrentServer() {
        let agoraURL = URL(string: "http://127.0.0.1:8000")!
        let volcengineURL = URL(string: "http://127.0.0.1:8001")!
        let agora = SDKCapability(sdk: "agora_rtc", interfaces: [])
        let volcengine = SDKCapability(sdk: "volcengine_rtc", interfaces: [])

        let selected = SDKRouteSelection.automaticallyAlignedSDK(
            capabilities: [agora, volcengine],
            routes: [
                agora.sdk: SDKRoute(url: agoraURL, nodeID: "mac-agora"),
                volcengine.sdk: SDKRoute(url: volcengineURL, nodeID: "mac-volcengine"),
            ],
            serverURL: volcengineURL
        )

        XCTAssertEqual(selected?.sdk, "volcengine_rtc")
    }
}
