import Foundation
import XCTest
@testable import BeaconMacTestConsole

final class RunHistoryPresenterTests: XCTestCase {
    func testCreatedTimeConvertsEpochMillisecondsToLocalClockText() {
        let milliseconds = 1_757_600_001_500
        // 期望值用同格式的独立 formatter 生成：断言钉住的是毫秒换算与文案格式，而不是运行机器的时区。
        let expectedFormatter = DateFormatter()
        expectedFormatter.dateFormat = "MM-dd HH:mm:ss"
        expectedFormatter.locale = Locale(identifier: "en_US_POSIX")
        let expectedDate = Date(timeIntervalSince1970: 1_757_600_001.5)

        XCTAssertEqual(RunHistoryPresenter.createdDate(milliseconds: milliseconds), expectedDate)
        XCTAssertEqual(RunHistoryPresenter.createdTimeText(milliseconds: milliseconds), expectedFormatter.string(from: expectedDate))
    }

    func testCaseCountTextKeepsSingularForSingleCaseRun() {
        XCTAssertEqual(RunHistoryPresenter.caseCountText([]), "0 cases")
        XCTAssertEqual(RunHistoryPresenter.caseCountText(["TC-MAC-SMOKE"]), "1 case")
        XCTAssertEqual(RunHistoryPresenter.caseCountText(["TC-1", "TC-2", "TC-3"]), "3 cases")
    }

    func testDurationTextFallsBackToPlaceholderForUnfinishedRun() {
        XCTAssertEqual(RunHistoryPresenter.durationText(of: makeSummary(durationMs: nil)), "—")
        // server 只给非负时长；0 ms 走 `CaseRunPresenter` 的同一占位符，不显示成 "0 ms"。
        XCTAssertEqual(RunHistoryPresenter.durationText(of: makeSummary(durationMs: 0)), "—")
        XCTAssertEqual(RunHistoryPresenter.durationText(of: makeSummary(durationMs: 50)), "50 ms")
        XCTAssertEqual(RunHistoryPresenter.durationText(of: makeSummary(durationMs: 1200)), "1200 ms")
    }

    private func makeSummary(durationMs: Int?) -> RunHistorySummary {
        RunHistorySummary(
            runID: "run-1",
            status: durationMs == nil ? "running" : "passed",
            caseIDs: ["TC-MAC-SMOKE"],
            createdAtMs: 100,
            finishedAtMs: durationMs.map { 100 + $0 },
            durationMs: durationMs
        )
    }
}
