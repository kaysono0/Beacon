import XCTest
@testable import BeaconMacTestConsole

final class LogExpansionStateTests: XCTestCase {
    func testToggleExpandsThenCollapsesWithinTheSameRun() {
        var state = LogExpansionState()

        XCTAssertFalse(state.isExpanded("row-a", inRun: "run-1"))

        state.toggle("row-a", inRun: "run-1")
        XCTAssertTrue(state.isExpanded("row-a", inRun: "run-1"))
        XCTAssertEqual(state.expandedCount(inRun: "run-1"), 1)

        state.toggle("row-a", inRun: "run-1")
        XCTAssertFalse(state.isExpanded("row-a", inRun: "run-1"))
        XCTAssertEqual(state.expandedCount(inRun: "run-1"), 0)
    }

    func testExpansionIsScopedToTheRunSoBatchesDoNotLeakStateAcrossCases() {
        var state = LogExpansionState()

        state.toggle("row-a", inRun: "run-1")
        state.toggle("row-b", inRun: "run-2")

        // 一次 Run Suite 里每个 case 各是一个 run：切到下一个 case 时不能把上一个 run 的展开带过来。
        XCTAssertTrue(state.isExpanded("row-a", inRun: "run-1"))
        XCTAssertFalse(state.isExpanded("row-a", inRun: "run-2"))
        XCTAssertTrue(state.isExpanded("row-b", inRun: "run-2"))
        XCTAssertFalse(state.isExpanded("row-b", inRun: "run-1"))
    }

    func testSameRowIDInDifferentRunsDoesNotShareExpansion() {
        var state = LogExpansionState()

        // 行 id 可能在不同 run 里重复（例如无 event_id 的回退键），归属必须靠 run 区分。
        state.toggle("same-row", inRun: "run-1")

        XCTAssertTrue(state.isExpanded("same-row", inRun: "run-1"))
        XCTAssertFalse(state.isExpanded("same-row", inRun: "run-2"))
    }

    func testUnknownRunHasNoExpansion() {
        let state = LogExpansionState()

        XCTAssertFalse(state.isExpanded("row-a", inRun: "run-unknown"))
        XCTAssertEqual(state.expandedCount(inRun: "run-unknown"), 0)
    }

    func testEachRunKeepsItsOwnExpandedCount() {
        var state = LogExpansionState()

        state.toggle("row-a", inRun: "run-1")
        state.toggle("row-b", inRun: "run-1")
        state.toggle("row-c", inRun: "run-2")

        XCTAssertEqual(state.expandedCount(inRun: "run-1"), 2)
        XCTAssertEqual(state.expandedCount(inRun: "run-2"), 1)
    }
}
