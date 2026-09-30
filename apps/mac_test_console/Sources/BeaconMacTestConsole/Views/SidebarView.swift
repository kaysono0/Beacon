import SwiftUI

struct SidebarView: View {
    @ObservedObject var viewModel: ConsoleViewModel
    /// SDK 选择走调用方注入的动作：选中即切环境的路由由 RootView 承担。
    let onSelectSDK: (SDKCapability) -> Void

    var body: some View {
        List {
            Section("SDK") {
                ForEach(Array(viewModel.sdkCapabilities), id: \.sdk) { sdk in
                    SidebarSelectableRow(
                        title: sdk.sdk,
                        trailing: nil,
                        aggregate: nil,
                        isSelected: viewModel.selectedSDK?.sdk == sdk.sdk,
                        accessibilityIdentifier: "sdkRow_\(sdk.sdk)"
                    ) {
                        onSelectSDK(sdk)
                    }
                }
            }
            .disabled(viewModel.isRunning)
            Section("Suites") {
                ForEach(Array(viewModel.suites), id: \.name) { suite in
                    SidebarSelectableRow(
                        title: suite.name,
                        trailing: "\(suite.count)",
                        aggregate: suiteAggregate(suite.name),
                        isSelected: viewModel.selectedSuite == suite.name,
                        accessibilityIdentifier: "suiteRow_\(suite.name)"
                    ) {
                        viewModel.selectSuite(suite)
                    }
                }
            }
        }
        .navigationTitle("Beacon")
    }

    /// suite 聚合分母取 runnable case 数，与批量运行清单一致。
    private func suiteAggregate(_ suite: String) -> CaseRunPresenter.SuiteAggregate {
        CaseRunPresenter.suiteAggregate(
            of: viewModel.runnableCases(in: suite),
            results: viewModel.caseResults
        )
    }
}

private struct SidebarSelectableRow: View {
    let title: String
    let trailing: String?
    let aggregate: CaseRunPresenter.SuiteAggregate?
    let isSelected: Bool
    let accessibilityIdentifier: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack {
                Text(title)
                Spacer()
                // 有终态结果后 ✓ 承载结果语义，选中态改由系统高亮表达。
                if let aggregate, aggregate.done > 0 {
                    Text("\(aggregate.passed)/\(aggregate.total)")
                        .foregroundStyle(.secondary)
                    Image(systemName: CaseRunPresenter.aggregateSymbolName(aggregate))
                        .foregroundStyle(CaseRunPresenter.aggregateColor(aggregate))
                } else if let trailing {
                    Text(trailing)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityIdentifier)
        .listRowBackground(isSelected ? Color.accentColor.opacity(0.18) : nil)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}
