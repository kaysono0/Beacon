import SwiftUI

/// 报告区：状态 hero + gate chips + 计数分段条 + Raw 折叠，替代 summary 字典按序倾倒。
/// 提炼逻辑在 `ReportSummaryPresenter`，保持无 SwiftUI 依赖可单测。
struct ReportView: View {
    let detail: ConsoleRunDetail?
    @State private var showsRawSummary = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let detail {
                heroRow(status: detail.run.status, summary: detail.report.summary)
                metaRow(runID: detail.report.runID)
                gateChipsRow(detail.report.summary)
                rawSummarySection(detail.report.summary)
            } else {
                Text("No report")
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
    }

    private func heroRow(status: String, summary: [String: JSONValue]) -> some View {
        let counters = ReportSummaryPresenter.counters(from: summary)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: ReportSummaryPresenter.heroSymbolName(for: status))
                    .foregroundStyle(heroColor(status))
                Text(status.uppercased())
                    .font(.title3)
                    .fontWeight(.semibold)
                    .foregroundStyle(heroColor(status))
                Spacer()
                counterText(counters)
            }
            counterBar(counters)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("reportHero")
    }

    private func heroColor(_ status: String) -> Color {
        switch status {
        case "passed":
            return .green
        case "failed":
            return .red
        default:
            return .secondary
        }
    }

    private func counterText(_ counters: ReportSummaryPresenter.Counters) -> some View {
        let parts = [
            counters.passed.map { "\($0) passed" },
            counters.failed.map { "\($0) failed" },
            counters.unsupported.map { "\($0) unsupported" },
        ]
        .compactMap { $0 }
        return Text(parts.joined(separator: " · "))
            .font(.subheadline)
            .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private func counterBar(_ counters: ReportSummaryPresenter.Counters) -> some View {
        let passed = counters.passed ?? 0
        let failed = counters.failed ?? 0
        let unsupported = counters.unsupported ?? 0
        let total = counters.totalSteps ?? (passed + failed + unsupported)
        if total > 0 {
            GeometryReader { geo in
                HStack(spacing: 2) {
                    segment(passed, total: total, width: geo.size.width, color: .green)
                    segment(failed, total: total, width: geo.size.width, color: .red)
                    segment(unsupported, total: total, width: geo.size.width, color: .gray)
                }
            }
            .frame(height: 6)
        }
    }

    @ViewBuilder
    private func segment(_ value: Int, total: Int, width: CGFloat, color: Color) -> some View {
        if value > 0 {
            Capsule()
                .fill(color.opacity(0.85))
                .frame(width: max(4, width * CGFloat(value) / CGFloat(total) - 2))
        }
    }

    private func metaRow(runID: String) -> some View {
        HStack(spacing: 6) {
            Text("Report")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(runID)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(runID, forType: .string)
            } label: {
                Image(systemName: "doc.on.doc")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("Copy run ID")
            .accessibilityIdentifier("copyRunIDButton")
            .help("Copy run ID")
        }
    }

    @ViewBuilder
    private func gateChipsRow(_ summary: [String: JSONValue]) -> some View {
        let chips = ReportSummaryPresenter.gateChips(from: summary)
        if !chips.isEmpty {
            HStack(spacing: 6) {
                ForEach(chips, id: \.name) { chip in
                    HStack(spacing: 4) {
                        Image(systemName: ReportSummaryPresenter.gateSymbolName(for: chip.state))
                        Text("\(chip.name) \(chip.rawValue.isEmpty ? "—" : chip.rawValue)")
                    }
                    .font(.caption)
                    .foregroundStyle(foregroundColor(chip.state))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color(nsColor: .controlBackgroundColor))
                    .clipShape(Capsule())
                    .overlay(Capsule().strokeBorder(Color(nsColor: .separatorColor), lineWidth: 0.5))
                    .accessibilityIdentifier("gateChip_\(chip.name)")
                }
            }
        }
    }

    /// chip 颜色只区分通过与其他：失败不再标红，避免与报告 hero 的红色语义点重复。
    private func foregroundColor(_ state: ReportSummaryPresenter.GateState) -> Color {
        switch state {
        case .passed:
            return .green
        case .failed, .notApplicable:
            return .secondary
        }
    }

    private func rawSummarySection(_ summary: [String: JSONValue]) -> some View {
        DisclosureGroup(isExpanded: $showsRawSummary) {
            ForEach(summary.keys.sorted(), id: \.self) { key in
                HStack {
                    Text(key)
                        .font(.caption)
                    Spacer()
                    Text(rawValueOrDash(summary[key]))
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
        } label: {
            Text("Raw summary (\(summary.count) keys)")
                .font(.subheadline)
                .fontWeight(.medium)
        }
        .accessibilityIdentifier("rawReportSummary")
    }

    private func rawValueOrDash(_ value: JSONValue?) -> String {
        let raw = value?.displayValue ?? ""
        return raw.isEmpty ? "—" : raw
    }
}

/// 从 report summary 提炼 gate chips、计数与 hero 符号的纯函数集合。
enum ReportSummaryPresenter {
    struct Counters: Equatable {
        let passed: Int?
        let failed: Int?
        let unsupported: Int?
        let totalSteps: Int?
    }

    enum GateState: Equatable {
        case passed
        case failed
        case notApplicable
    }

    struct GateChip: Equatable {
        let name: String
        let rawValue: String
        let state: GateState
    }

    static func counters(from summary: [String: JSONValue]) -> Counters {
        Counters(
            passed: intValue("passed", summary),
            failed: intValue("failed", summary),
            unsupported: intValue("unsupported", summary),
            totalSteps: intValue("total_steps", summary)
        )
    }

    static func gateChips(from summary: [String: JSONValue]) -> [GateChip] {
        summary
            .filter { $0.key.hasSuffix("_gate_status") }
            .sorted { $0.key < $1.key }
            .map { key, value in
                GateChip(
                    name: String(key.dropLast("_gate_status".count)),
                    rawValue: value.displayValue,
                    state: gateState(value.displayValue)
                )
            }
    }

    static func heroSymbolName(for status: String) -> String {
        switch status {
        case "passed":
            return "checkmark.circle.fill"
        case "failed":
            return "xmark.octagon.fill"
        case "canceled", "cancelled":
            return "minus.circle.fill"
        default:
            // running/queued 等非终态
            return "ellipsis.circle"
        }
    }

    static func gateSymbolName(for state: GateState) -> String {
        switch state {
        case .passed:
            return "checkmark.circle.fill"
        case .failed:
            return "xmark.octagon.fill"
        case .notApplicable:
            return "minus.circle"
        }
    }

    private static func gateState(_ raw: String) -> GateState {
        switch raw.lowercased() {
        case "passed":
            return .passed
        case "failed":
            return .failed
        default:
            // not_applicable、空值与未知值统一走中性态，chip 文本仍显示原值
            return .notApplicable
        }
    }

    private static func intValue(_ key: String, _ summary: [String: JSONValue]) -> Int? {
        summary[key]?.intValue
    }
}
