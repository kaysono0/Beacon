import XCTest
@testable import BeaconMacTestConsole

final class ReportSummaryPresenterTests: XCTestCase {
    func testCountersExtractsIntegerSummaryKeys() {
        let summary: [String: JSONValue] = [
            "passed": .int(21),
            "failed": .int(0),
            "unsupported": .int(2),
            "total_steps": .int(23),
            "status": .string("passed"),
        ]
        let counters = ReportSummaryPresenter.counters(from: summary)
        XCTAssertEqual(counters.passed, 21)
        XCTAssertEqual(counters.failed, 0)
        XCTAssertEqual(counters.unsupported, 2)
        XCTAssertEqual(counters.totalSteps, 23)
    }

    func testCountersMissingKeysAreNil() {
        let counters = ReportSummaryPresenter.counters(from: [:])
        XCTAssertNil(counters.passed)
        XCTAssertNil(counters.failed)
        XCTAssertNil(counters.unsupported)
        XCTAssertNil(counters.totalSteps)
    }

    func testGateChipsExtractOnlyGateStatusKeysSortedByName() {
        let summary: [String: JSONValue] = [
            "resilience_gate_status": .string("not_applicable"),
            "core_gate_status": .string("passed"),
            "enhanced_gate_status": .string(""),
            "passed": .int(3),
        ]
        let chips = ReportSummaryPresenter.gateChips(from: summary)
        XCTAssertEqual(chips.map(\.name), ["core", "enhanced", "resilience"])
        XCTAssertEqual(chips[0].rawValue, "passed")
        XCTAssertEqual(chips[1].rawValue, "")
        XCTAssertEqual(chips[2].rawValue, "not_applicable")
    }

    func testGateChipStateMapping() {
        let summary: [String: JSONValue] = [
            "a_gate_status": .string("passed"),
            "b_gate_status": .string("failed"),
            "c_gate_status": .string("not_applicable"),
            "d_gate_status": .null,
        ]
        let chips = ReportSummaryPresenter.gateChips(from: summary)
        XCTAssertEqual(chips[0].state, .passed)
        XCTAssertEqual(chips[1].state, .failed)
        XCTAssertEqual(chips[2].state, .notApplicable)
        XCTAssertEqual(chips[3].state, .notApplicable)
        XCTAssertEqual(chips[3].rawValue, "")
    }

    func testHeroSymbolNameCoversTerminalAndRunningStatuses() {
        XCTAssertEqual(ReportSummaryPresenter.heroSymbolName(for: "passed"), "checkmark.circle.fill")
        XCTAssertEqual(ReportSummaryPresenter.heroSymbolName(for: "failed"), "xmark.octagon.fill")
        XCTAssertEqual(ReportSummaryPresenter.heroSymbolName(for: "canceled"), "minus.circle.fill")
        XCTAssertEqual(ReportSummaryPresenter.heroSymbolName(for: "cancelled"), "minus.circle.fill")
        XCTAssertEqual(ReportSummaryPresenter.heroSymbolName(for: "running"), "ellipsis.circle")
        XCTAssertEqual(ReportSummaryPresenter.heroSymbolName(for: "queued"), "ellipsis.circle")
    }

    func testGateSymbolNameCoversAllStates() {
        XCTAssertEqual(ReportSummaryPresenter.gateSymbolName(for: .passed), "checkmark.circle.fill")
        XCTAssertEqual(ReportSummaryPresenter.gateSymbolName(for: .failed), "xmark.octagon.fill")
        XCTAssertEqual(ReportSummaryPresenter.gateSymbolName(for: .notApplicable), "minus.circle")
    }
}
