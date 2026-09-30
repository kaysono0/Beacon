import SwiftUI

/// case/run 状态到图标、颜色与耗时的纯映射，供 case 列表、侧栏 suite 行、
/// suite 运行清单与 run 详情共用。
///
/// 本类型不持状态、不依赖视图层级，可直接单测；状态词汇与 `ReportSummaryPresenter` 保持一致。
enum CaseRunPresenter {
    /// suite 聚合计数：`total` 为 runnable case 数，`done` 只统计已到终态的 case。
    struct SuiteAggregate: Equatable {
        let done: Int
        let total: Int
        let passed: Int
        let failed: Int
    }

    /// `status` 为 nil 表示本会话尚未运行该 case，使用虚线占位而不是任何结果语义。
    static func symbolName(for status: String?) -> String {
        switch status {
        case "passed":
            return "checkmark.circle.fill"
        case "failed":
            return "xmark.circle.fill"
        case "running":
            return "circle.dotted"
        case "queued":
            return "clock"
        case "canceled", "cancelled":
            return "minus.circle.fill"
        case nil:
            return "circle.dashed"
        default:
            return "ellipsis.circle"
        }
    }

    static func color(for status: String?) -> Color {
        switch status {
        case "passed":
            return .green
        case "failed":
            return .red
        case "running":
            return .accentColor
        default:
            return .secondary
        }
    }

    /// 非用例列表上下文的状态色：红色只保留用例列表状态点与报告 hero 两处语义点，
    /// 其余位置的失败态一律中性色，避免整屏红色报警噪声。
    static func quietColor(for status: String?) -> Color {
        switch status {
        case "passed":
            return .green
        case "running":
            return .accentColor
        default:
            return .secondary
        }
    }

    /// `RunResponse` 没有总时长字段，用各 step 的 `duration_ms` 求和作为近似值；
    /// 步骤之间的调度与等待间隙不计入。
    static func totalDurationMs(of run: RunResponse) -> Int {
        run.stepResults.reduce(0) { $0 + $1.durationMs }
    }

    static func durationText(of run: RunResponse) -> String {
        durationText(milliseconds: totalDurationMs(of: run))
    }

    static func durationText(milliseconds: Int) -> String {
        milliseconds > 0 ? "\(milliseconds) ms" : "—"
    }

    /// 分母只计 runnable case：非 runnable case 永远不会有结果，计入分母后聚合永远小于 1。
    /// 不属于 `cases` 的结果（例如非 runnable case 的历史结果）不参与计数。
    static func suiteAggregate(
        of cases: [TestCaseSummary],
        results: [String: RunResponse]
    ) -> SuiteAggregate {
        let runs = cases.compactMap { results[$0.caseID] }
        return SuiteAggregate(
            done: runs.filter(\.isTerminal).count,
            total: cases.count,
            passed: runs.filter { $0.status == "passed" }.count,
            failed: runs.filter { $0.status == "failed" }.count
        )
    }

    /// 聚合图标：有失败转叉、全通过绿勾；只有 canceled 等无通过结果时用中性图标，
    /// 避免绿勾出现在 0 passed 的计数旁。颜色走中性策略，失败不标红。
    static func aggregateSymbolName(_ aggregate: SuiteAggregate) -> String {
        if aggregate.failed > 0 {
            return "xmark.circle.fill"
        }
        if aggregate.passed > 0 {
            return "checkmark.circle.fill"
        }
        return "minus.circle.fill"
    }

    static func aggregateColor(_ aggregate: SuiteAggregate) -> Color {
        if aggregate.failed > 0 {
            return .secondary
        }
        if aggregate.passed > 0 {
            return .green
        }
        return .secondary
    }
}
