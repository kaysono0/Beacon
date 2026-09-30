import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// 日志排查面板：失败摘要置顶，支持 level/step/关键字过滤与生命周期日志折叠。
struct LogPanelView: View {
    @ObservedObject var viewModel: ConsoleViewModel
    @State private var expansion = LogExpansionState()

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            headerRow
            failureSummaryCard
            filterControlsRow
            if viewModel.hiddenLifecycleLogCount > 0 {
                lifecycleToggleButton
            }
            keyEventsSection
            logList
        }
        .padding()
    }

    private var headerRow: some View {
        HStack(spacing: 10) {
            Text("Logs")
                .font(.headline)
            Text("\(viewModel.filteredLogs.count)")
                .foregroundStyle(.secondary)
            Spacer()
            Button {
                copyVisibleLogs()
            } label: {
                Image(systemName: "doc.on.doc")
            }
            .buttonStyle(.borderless)
            .disabled(viewModel.filteredLogs.isEmpty)
            .accessibilityLabel("Copy visible logs")
            .accessibilityIdentifier("copyLogsButton")
            .help("Copy visible logs")
            Button {
                saveVisibleLogs()
            } label: {
                Image(systemName: "square.and.arrow.down")
            }
            .buttonStyle(.borderless)
            .disabled(viewModel.filteredLogs.isEmpty)
            .accessibilityLabel("Save visible logs")
            .accessibilityIdentifier("saveLogsButton")
            .help("Save visible logs as .log")
        }
    }

    @ViewBuilder
    private var failureSummaryCard: some View {
        if !viewModel.failedStepResults.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(viewModel.failedStepResults) { result in
                    failedStepRow(result)
                }
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .accessibilityIdentifier("failureSummaryCard")
        }
    }

    private var filterControlsRow: some View {
        HStack(spacing: 10) {
            Picker("Level", selection: $viewModel.logLevelFilter) {
                ForEach(LogLevelFilter.allCases) { level in
                    Text(level.label).tag(level)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 220)
            .accessibilityIdentifier("logLevelFilterPicker")

            Picker("Step", selection: $viewModel.logStepFilter) {
                Text("All Steps").tag(String?.none)
                ForEach(viewModel.stepFilterOptions, id: \.self) { stepID in
                    Text(stepID).tag(String?.some(stepID))
                }
            }
            .frame(maxWidth: 260)
            .accessibilityIdentifier("logStepFilterPicker")

            TextField("Filter logs", text: $viewModel.logFilter)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 280)
        }
    }

    private var lifecycleToggleButton: some View {
        Button {
            viewModel.showsLifecycleLogs.toggle()
        } label: {
            Text(
                viewModel.showsLifecycleLogs
                    ? "Hide \(viewModel.hiddenLifecycleLogCount) server lifecycle logs"
                    : "Show \(viewModel.hiddenLifecycleLogCount) server lifecycle logs"
            )
            .font(.caption)
        }
        .buttonStyle(.borderless)
        .accessibilityIdentifier("logLifecycleToggleButton")
    }

    @ViewBuilder
    private var keyEventsSection: some View {
        // Key Events 是全局策展视图，刻意不受 level/step/文本过滤影响。
        if !viewModel.keyLogRows.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Key Events")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                    Text("\(viewModel.keyLogRows.count)")
                        .foregroundStyle(.secondary)
                }
                ForEach(viewModel.keyLogRows.suffix(6)) { row in
                    keyPreviewRow(row)
                }
            }
            .padding(8)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 6))
        }
    }

    private var logList: some View {
        List(viewModel.filteredLogs) { row in
            logRow(row)
        }
    }

    private func failedStepRow(_ result: StepResultSummary) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 8) {
                Image(systemName: "xmark.octagon")
                    .foregroundStyle(.secondary)
                Text(result.stepID)
                    .font(.subheadline)
                    .fontWeight(.semibold)
                if let code = result.errorCode {
                    Text("code \(code)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let offset = viewModel.failureOffsetText(for: result) {
                    Text(offset)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(viewModel.logStepFilter == result.stepID ? "Clear Step Filter" : "View Step Logs") {
                    viewModel.toggleStepFilter(result.stepID)
                }
                .buttonStyle(.borderless)
                .accessibilityIdentifier("failureStepLogsButton_\(result.stepID)")
            }
            if !result.message.isEmpty {
                Text(result.message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
    }

    private func logRow(_ row: LogRow) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(row.timestamp.map { ConsoleViewModel.timeText(from: $0) } ?? "—")
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .frame(width: 84, alignment: .leading)
                Text(row.level.uppercased())
                    .font(.caption2)
                    .foregroundStyle(levelColor(row.level))
                    .frame(width: 56, alignment: .leading)
                Text(row.operation)
                    .font(.body)
                    .fontWeight(.medium)
                    .lineLimit(1)
                    .textSelection(.enabled)
                Text(row.outcome)
                    .font(.subheadline)
                    .foregroundStyle(levelColor(row.level))
                    .lineLimit(1)
                    .textSelection(.enabled)
                Spacer()
                if !row.detail.isEmpty {
                    Button {
                        toggleExpanded(row)
                    } label: {
                        Text(isExpanded(row) ? "Hide" : "Details")
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(isExpanded(row) ? "Hide log details" : "Show log details")
                }
            }
            if isExpanded(row), !row.detail.isEmpty {
                Text(row.detail)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(.vertical, 4)
    }

    private func keyPreviewRow(_ row: LogRow) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(row.level.uppercased())
                .font(.caption2)
                .foregroundStyle(row.level == "error" ? Color.red : Color.secondary)
                .frame(width: 52, alignment: .leading)
            Text(row.operation)
                .font(.caption)
                .lineLimit(1)
                .textSelection(.enabled)
            Text(row.outcome)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .textSelection(.enabled)
            Spacer()
        }
    }

    private func levelColor(_ level: String) -> Color {
        switch level.lowercased() {
        case "error":
            return .red
        case "warning", "warn":
            return .orange
        default:
            return .secondary
        }
    }

    private func toggleExpanded(_ row: LogRow) {
        expansion.toggle(row.id, inRun: currentRunKey)
    }

    /// 展开状态按 run 归属：批量运行会在不同 run 之间切换展示，跨 run 共用会串状态。
    private var currentRunKey: String {
        viewModel.currentRun?.runID ?? ""
    }

    private func isExpanded(_ row: LogRow) -> Bool {
        expansion.isExpanded(row.id, inRun: currentRunKey)
    }

    private func copyVisibleLogs() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(viewModel.visibleLogsText(), forType: .string)
    }

    private func saveVisibleLogs() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.plainText]
        panel.nameFieldStringValue = "\(viewModel.currentRunDetail?.run.runID ?? "beacon-run").log"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try viewModel.visibleLogsText().write(to: url, atomically: true, encoding: .utf8)
        } catch {
            viewModel.errorMessage = String(describing: error)
        }
    }
}
