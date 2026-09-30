import SwiftUI

struct RunDetailView: View {
    let run: RunResponse?
    var observationCursorEnabled = false
    var observations: [ConsoleObservation] = []
    var observationError: String?
    var onToggleStepFilter: (String) -> Void = { _ in }

    private var executionObservations: [ConsoleObservation] {
        observations.filter(\.isExecutionRecord)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let run {
                Text("Execution records")
                    .font(.headline)
                List {
                    if observationCursorEnabled {
                        if let observationError {
                            Text(observationError).foregroundStyle(.red)
                        } else if executionObservations.isEmpty {
                            Text("No execution records").foregroundStyle(.secondary)
                        }
                        ForEach(executionObservations) { observation in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(observation.title)
                                    .font(.subheadline)
                                Text(observation.detailText)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    } else {
                        ForEach(Array(run.stepResults.enumerated()), id: \.offset) { _, result in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    if result.status == "failed" {
                                        Button {
                                            onToggleStepFilter(result.stepID)
                                        } label: {
                                            HStack(spacing: 4) {
                                                Image(systemName: "line.3.horizontal.decrease.circle")
                                                Text(result.stepID)
                                            }
                                        }
                                        .buttonStyle(.plain)
                                        .accessibilityLabel("Filter logs for step \(result.stepID)")
                                        .accessibilityIdentifier("stepRow_\(result.stepID)")
                                    } else {
                                        Text(result.stepID)
                                    }
                                    Spacer()
                                    stepStatusRow(result.status)
                                    if result.status == "passed" {
                                        if !result.durationLabel.isEmpty {
                                            Text(result.durationLabel)
                                                .foregroundStyle(.secondary)
                                        }
                                    } else if let errorCode = result.errorCode {
                                        Text("\(errorCode)")
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                if result.status != "passed", !result.message.isEmpty {
                                    Text(result.message)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .textSelection(.enabled)
                                }
                            }
                        }
                    }
                }
                .frame(height: 150)
            } else {
                Text("No run selected")
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// step 级状态：与用例列表共用图标词汇，颜色走中性策略（红色只留在用例列表与报告 hero）。
    private func stepStatusRow(_ status: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: CaseRunPresenter.symbolName(for: status))
                .foregroundStyle(CaseRunPresenter.quietColor(for: status))
            Text(status)
        }
    }
}
