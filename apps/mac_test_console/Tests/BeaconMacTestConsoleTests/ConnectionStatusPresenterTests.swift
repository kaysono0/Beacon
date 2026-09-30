import XCTest
import SwiftUI
@testable import BeaconMacTestConsole

final class ConnectionStatusPresenterTests: XCTestCase {
    func testColorEncodesConnectionConclusion() {
        XCTAssertEqual(ConnectionStatusPresenter.color(for: .connected(version: "0.1.0-p0")), .green)
        XCTAssertEqual(ConnectionStatusPresenter.color(for: .connecting), .yellow)
        XCTAssertEqual(ConnectionStatusPresenter.color(for: .failed(message: "boom")), .red)
        XCTAssertEqual(ConnectionStatusPresenter.color(for: .disconnected), .secondary)
    }

    func testTextGivesShortConclusionWithCaseCount() {
        XCTAssertEqual(ConnectionStatusPresenter.text(for: .connected(version: "0.1.0-p0"), caseCount: 41), "Connected (41 cases)")
        XCTAssertEqual(ConnectionStatusPresenter.text(for: .connected(version: "0.1.0-p0"), caseCount: 0), "Connected (0 cases)")
        XCTAssertEqual(ConnectionStatusPresenter.text(for: .connecting, caseCount: 41), "Connecting…")
        XCTAssertEqual(ConnectionStatusPresenter.text(for: .disconnected, caseCount: 0), "Disconnected")
    }

    func testTextKeepsFullErrorMessageOutOfConnectionBar() {
        // 完整错误文本由详情区 connectionErrorText 承载，连接栏只给结论。
        XCTAssertEqual(
            ConnectionStatusPresenter.text(for: .failed(message: "HTTP 401: auth token is missing or invalid"), caseCount: 0),
            "Connection failed"
        )
    }

    func testAccessibilityLabelAddsServerVersionOnlyWhenConnected() {
        XCTAssertEqual(
            ConnectionStatusPresenter.accessibilityLabel(for: .connected(version: "0.1.0-p0"), caseCount: 41),
            "Connected to Beacon Server 0.1.0-p0, 41 cases loaded"
        )
        XCTAssertEqual(ConnectionStatusPresenter.accessibilityLabel(for: .connecting, caseCount: 41), "Connecting…")
        XCTAssertEqual(ConnectionStatusPresenter.accessibilityLabel(for: .failed(message: "boom"), caseCount: 0), "Connection failed")
        XCTAssertEqual(ConnectionStatusPresenter.accessibilityLabel(for: .disconnected, caseCount: 0), "Disconnected")
    }
}
