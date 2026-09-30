import XCTest
@testable import BeaconMacTestConsole

@MainActor
final class CatalogSelectionTests: XCTestCase {
    func testSynchronizeResetsUnavailableSuiteAndCase() {
        let cases = [
            TestCaseSummary(caseID: "alpha-1", name: "Alpha", platform: "mac", suite: "alpha", tags: []),
            TestCaseSummary(caseID: "beta-1", name: "Beta", platform: "mac", suite: "beta", tags: []),
        ]
        let state = CatalogSelection.State(selectedSDK: nil, selectedSuite: "missing", selectedCase: cases[1])

        let resolved = CatalogSelection.synchronized(state, testCases: cases)

        XCTAssertEqual(resolved.selectedSuite, "alpha")
        XCTAssertEqual(resolved.selectedCase?.caseID, "alpha-1")
    }

    func testDefaultSDKAndSuiteOrderAreStable() {
        let capabilities = [SDKCapability(sdk: "volcengine", interfaces: []), SDKCapability(sdk: "agora", interfaces: [])]
        let cases = [
            TestCaseSummary(caseID: "b", name: "B", platform: "mac", suite: "suite-b", tags: []),
            TestCaseSummary(caseID: "a", name: "A", platform: "mac", suite: "suite-a", tags: []),
        ]

        XCTAssertEqual(CatalogSelection.defaultSDK(in: capabilities)?.sdk, "agora")
        XCTAssertEqual(CatalogSelection.suites(cases, sdk: nil).map(\.name), ["suite-a", "suite-b"])
    }
}
