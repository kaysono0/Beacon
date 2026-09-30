import SwiftUI

/// server 端运行历史的 sheet：按创建时间倒序列出 run 摘要，点行回看该 run 并关闭 sheet。
///
/// 视图自身不持状态，数据源是 `ConsoleViewModel.runHistory`；回看复用 `openRun` 路径，
/// 因此历史里的 run 与刚跑完的 run 在详情区呈现一致。
struct RunHistoryView: View {
    let entries: [RunHistorySummary]
    let onOpenRun: (String) -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if entries.isEmpty {
                emptyState
            } else {
                List {
                    ForEach(entries) { entry in
                        row(entry)
                    }
                }
                .accessibilityIdentifier("runHistoryList")
            }
        }
        .frame(width: 660, height: 440)
        .accessibilityIdentifier("runHistorySheet")
    }

    private var header: some View {
        HStack(spacing: 6) {
            Text("Run history")
                .font(.headline)
            Text("(\(entries.count))")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .accessibilityIdentifier("runHistoryCount")
            Spacer()
            Button("Done", action: onDismiss)
                .keyboardShortcut(.cancelAction)
                .accessibilityLabel("Done")
                .accessibilityIdentifier("runHistoryDoneButton")
        }
        .padding(12)
    }

    private var emptyState: some View {
        VStack(spacing: 6) {
            Text("No runs recorded yet")
                .foregroundStyle(.secondary)
            Text("Runs created on this server show up here, and survive an app restart.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
        .accessibilityIdentifier("runHistoryEmptyText")
    }

    private func row(_ entry: RunHistorySummary) -> some View {
        Button {
            onOpenRun(entry.runID)
        } label: {
            HStack(spacing: 8) {
                Image(systemName: CaseRunPresenter.symbolName(for: entry.status))
                    .foregroundStyle(CaseRunPresenter.color(for: entry.status))
                    .accessibilityIdentifier("runHistoryStatus_\(entry.runID)")
                Text(entry.runID)
                    .font(.system(.caption, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .frame(width: 210, alignment: .leading)
                Text(RunHistoryPresenter.caseCountText(entry.caseIDs))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Text(RunHistoryPresenter.createdTimeText(milliseconds: entry.createdAtMs))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(RunHistoryPresenter.durationText(of: entry))
                    .font(.caption)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .frame(width: 76, alignment: .trailing)
            }
            .padding(.vertical, 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Open run \(entry.runID), status \(entry.status)")
        .accessibilityIdentifier("runHistoryRow_\(entry.runID)")
    }
}
