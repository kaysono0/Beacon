import XCTest
import SwiftUI
@testable import BeaconMacTestConsole

final class CaseRunPresenterTests: XCTestCase {
    func testSymbolNameCoversAllStatusesAndPlaceholder() {
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "passed"), "checkmark.circle.fill")
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "failed"), "xmark.circle.fill")
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "running"), "circle.dotted")
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "queued"), "clock")
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "canceled"), "minus.circle.fill")
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "cancelled"), "minus.circle.fill")
        XCTAssertEqual(CaseRunPresenter.symbolName(for: "unknown_state"), "ellipsis.circle")
        // 会话内未运行的 case 必须是占位形，不得借用任何结果语义图标。
        XCTAssertEqual(CaseRunPresenter.symbolName(for: nil), "circle.dashed")
    }

    func testColorEncodesStatusAlongsideSymbol() {
        XCTAssertEqual(CaseRunPresenter.color(for: "passed"), .green)
        XCTAssertEqual(CaseRunPresenter.color(for: "failed"), .red)
        XCTAssertEqual(CaseRunPresenter.color(for: "running"), .accentColor)
        XCTAssertEqual(CaseRunPresenter.color(for: "queued"), .secondary)
        XCTAssertEqual(CaseRunPresenter.color(for: "canceled"), .secondary)
        XCTAssertEqual(CaseRunPresenter.color(for: "unknown_state"), .secondary)
        XCTAssertEqual(CaseRunPresenter.color(for: nil), .secondary)
    }

    /// 非用例列表上下文（suite 运行清单、run 详情 step 行）不标红：红色只在用例列表与报告 hero。
    func testQuietColorKeepsFailureNeutral() {
        XCTAssertEqual(CaseRunPresenter.quietColor(for: "passed"), .green)
        XCTAssertEqual(CaseRunPresenter.quietColor(for: "failed"), .secondary)
        XCTAssertEqual(CaseRunPresenter.quietColor(for: "running"), .accentColor)
        XCTAssertEqual(CaseRunPresenter.quietColor(for: "queued"), .secondary)
        XCTAssertEqual(CaseRunPresenter.quietColor(for: "canceled"), .secondary)
        XCTAssertEqual(CaseRunPresenter.quietColor(for: nil), .secondary)
    }

    func testDurationSumsStepDurationsAndFallsBackToPlaceholder() {
        let run = makeRun(runID: "run-1", status: "passed", durationsMs: [1200, 300])
        XCTAssertEqual(CaseRunPresenter.totalDurationMs(of: run), 1500)
        XCTAssertEqual(CaseRunPresenter.durationText(of: run), "1500 ms")

        let emptyRun = makeRun(runID: "run-2", status: "queued", durationsMs: [])
        XCTAssertEqual(CaseRunPresenter.totalDurationMs(of: emptyRun), 0)
        XCTAssertEqual(CaseRunPresenter.durationText(of: emptyRun), "—")
        XCTAssertEqual(CaseRunPresenter.durationText(milliseconds: 0), "—")
    }

    func testSuiteAggregateCountsOnlyTerminalRunsOfListedCases() {
        let cases = [makeCase("TC-A"), makeCase("TC-B"), makeCase("TC-C")]
        let results = [
            "TC-A": makeRun(runID: "run-a", status: "passed", durationsMs: [10]),
            "TC-B": makeRun(runID: "run-b", status: "running", durationsMs: [10]),
            "TC-C": makeRun(runID: "run-c", status: "failed", durationsMs: [10]),
            // 不在清单内的结果（例如非 runnable case 的历史结果）不参与聚合计数。
            "TC-RETIRED": makeRun(runID: "run-x", status: "failed", durationsMs: [10]),
        ]

        let aggregate = CaseRunPresenter.suiteAggregate(of: cases, results: results)
        XCTAssertEqual(aggregate, CaseRunPresenter.SuiteAggregate(done: 2, total: 3, passed: 1, failed: 1))
    }

    func testSuiteAggregateWithoutResultsIsNotDone() {
        let cases = [makeCase("TC-A"), makeCase("TC-B")]
        let aggregate = CaseRunPresenter.suiteAggregate(of: cases, results: [:])
        XCTAssertEqual(aggregate, CaseRunPresenter.SuiteAggregate(done: 0, total: 2, passed: 0, failed: 0))
    }

    func testAggregateIconPrefersFailureOverPass() {
        let allPassed = CaseRunPresenter.SuiteAggregate(done: 2, total: 2, passed: 2, failed: 0)
        XCTAssertEqual(CaseRunPresenter.aggregateSymbolName(allPassed), "checkmark.circle.fill")
        XCTAssertEqual(CaseRunPresenter.aggregateColor(allPassed), .green)

        let oneFailed = CaseRunPresenter.SuiteAggregate(done: 2, total: 2, passed: 1, failed: 1)
        XCTAssertEqual(CaseRunPresenter.aggregateSymbolName(oneFailed), "xmark.circle.fill")
        // 侧栏不再用红色报警：失败态聚合色保持中性。
        XCTAssertEqual(CaseRunPresenter.aggregateColor(oneFailed), .secondary)

        // 只有 canceled 等终态、没有通过结果时不得显示绿勾。
        let onlyCanceled = CaseRunPresenter.SuiteAggregate(done: 1, total: 2, passed: 0, failed: 0)
        XCTAssertEqual(CaseRunPresenter.aggregateSymbolName(onlyCanceled), "minus.circle.fill")
        XCTAssertEqual(CaseRunPresenter.aggregateColor(onlyCanceled), .secondary)
    }

    private func makeCase(_ caseID: String) -> TestCaseSummary {
        TestCaseSummary(caseID: caseID, name: caseID, platform: "mac", suite: "suite-a", tags: [])
    }

    private func makeRun(runID: String, status: String, durationsMs: [Int]) -> RunResponse {
        RunResponse(
            runID: runID,
            status: status,
            stepResults: durationsMs.enumerated().map { index, durationMs in
                StepResultSummary(
                    caseID: "TC-A",
                    stepID: "step-\(index)",
                    status: status,
                    error: nil,
                    artifacts: [],
                    durationMs: durationMs
                )
            }
        )
    }
}
