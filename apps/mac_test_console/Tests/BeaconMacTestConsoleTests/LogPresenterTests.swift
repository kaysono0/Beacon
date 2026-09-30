import XCTest

@testable import BeaconMacTestConsole

@MainActor
final class LogPresenterTests: XCTestCase {
    func testFilteredCombinesLifecycleLevelStepAndTextRules() {
        let rows = [
            LogRow(level: "error", message: "dispatch failed", nodeID: "node-a", event: "assertion_failed", stepID: "step-1"),
            LogRow(level: "info", message: "started", nodeID: "node-a", event: "native.run.started", stepID: "step-1"),
            LogRow(level: "warning", message: "retrying", nodeID: "node-b", event: "sdk_call_dispatched", stepID: "step-2"),
        ]

        let filtered = LogPresenter.filtered(
            rows,
            text: "dispatch",
            level: .error,
            stepID: "step-1",
            showsLifecycle: false
        )

        XCTAssertEqual(filtered.map(\.message), ["dispatch failed"])
    }

    func testVisibleTextUsesStableLineFormatting() {
        let row = LogRow(
            level: "error",
            message: "request rejected",
            nodeID: "agent-1",
            event: "sdk_call_completed",
            detail: "op_id=op-7",
            module: "runtime"
        )

        XCTAssertEqual(
            LogPresenter.visibleText([row]),
            "ERROR sdk_call_completed request rejected op_id=op-7"
        )
    }

    func testNativeStepProjectionPrioritizesOperationAndOutcomeOverEventName() {
        let detail = ConsoleRunDetail(
            run: RunResponse(runID: "run-1", status: "passed", stepResults: []),
            report: ReportSummary(runID: "run-1", format: "json", summary: [:]),
            logs: [
                [
                    "level": .string("info"),
                    "event": .string("native.step.dispatching"),
                    "message": .string("python-native step dispatching protocol operations"),
                    "step_id": .string("join"),
                    "extra": .object([
                        "operation_targets": .array([
                            .object([
                                "op_id": .string("op-1"),
                                "target": .object(["function": .string("joinChannel")]),
                            ]),
                        ]),
                    ]),
                ],
                [
                    "level": .string("info"),
                    "event": .string("native.step.recorded"),
                    "message": .string("python-native step result recorded"),
                    "step_id": .string("join"),
                    "extra": .object(["status": .string("passed"), "node_id": .string("mac-1")]),
                ],
            ]
        )

        let rows = LogPresenter.rows(from: detail)

        XCTAssertEqual(rows.map(\.operation), ["joinChannel", "joinChannel"])
        XCTAssertEqual(rows.map(\.outcome), ["Dispatched", "Passed"])
        XCTAssertTrue(rows[0].detail.contains("event=native.step.dispatching"))
        XCTAssertTrue(rows[0].detail.contains("op_id:op-1"))
    }
}
